# dashboard/onboarding.py
# ════════════════════════════════════════════════════════════════
# YieldIQ — First-Run Onboarding Wizard
#
# 3-step wizard auto-shown to new users after first login.
# Progress and completion state stored in portfolio.db.
#
# Public API (called from app.py):
#   init_onboarding_db()      — call once at startup
#   maybe_show_wizard()       — call in main body after init_tier()
#   render_resume_button()    — call in sidebar
#   tooltip(key)              — returns help= string for st.metric / st.number_input
#   show_tooltips()           — True if user is in first-run mode
# ════════════════════════════════════════════════════════════════

from __future__ import annotations
import sqlite3
import pathlib
import threading
from datetime import datetime

import streamlit as st

# ── same portfolio.db used by the rest of the app ────────────
_DB_PATH = pathlib.Path(__file__).parent / "portfolio.db"
_lock    = threading.Lock()

# ── session-state keys ───────────────────────────────────────
_SHOW_KEY  = "_onboarding_show"   # bool  — render wizard this frame
_STEP_KEY  = "_onboarding_step"   # int   — current step 1–3
_DONE_KEY  = "_onboarding_done"   # bool  — skip all DB checks this session
_INIT_KEY  = "_onboarding_init"   # bool  — already ran maybe_show_wizard once

_TOTAL_STEPS = 3


# ════════════════════════════════════════════════════════════════
# DB HELPERS
# ════════════════════════════════════════════════════════════════

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_onboarding_db() -> None:
    """Create user_onboarding table if it doesn't exist. Safe to call on every startup."""
    with _lock:
        c = _conn()
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_onboarding (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email           TEXT    UNIQUE NOT NULL,
                onboarding_completed INTEGER DEFAULT 0,
                last_step            INTEGER DEFAULT 1,
                completed_at         TEXT,
                created_at           TEXT    NOT NULL
            )
        """)
        c.commit()
        c.close()


def _upsert_row(email: str) -> None:
    """Ensure a row exists for this user."""
    with _lock:
        c = _conn()
        c.execute(
            "INSERT OR IGNORE INTO user_onboarding (user_email, created_at) VALUES (?, ?)",
            (email, datetime.utcnow().isoformat()),
        )
        c.commit()
        c.close()


def is_onboarding_completed(email: str) -> bool:
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT onboarding_completed FROM user_onboarding WHERE user_email=?",
            (email,),
        ).fetchone()
        c.close()
    return bool(row and row["onboarding_completed"])


def _get_last_step(email: str) -> int:
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT last_step FROM user_onboarding WHERE user_email=?", (email,)
        ).fetchone()
        c.close()
    return int(row["last_step"]) if row else 1


def _save_progress(email: str, step: int) -> None:
    _upsert_row(email)
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE user_onboarding SET last_step=? WHERE user_email=?",
            (step, email),
        )
        c.commit()
        c.close()


def mark_onboarding_completed(email: str) -> None:
    _upsert_row(email)
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE user_onboarding SET onboarding_completed=1, completed_at=? WHERE user_email=?",
            (datetime.utcnow().isoformat(), email),
        )
        c.commit()
        c.close()
    st.session_state[_DONE_KEY] = True
    st.session_state[_SHOW_KEY] = False


# ════════════════════════════════════════════════════════════════
# METRIC TOOLTIPS
# ════════════════════════════════════════════════════════════════

METRIC_TOOLTIPS: dict[str, str] = {
    # Valuation
    "price":         "Current market price fetched live from Yahoo Finance.",
    "iv":            "Intrinsic Value — the DCF-derived fair value per share under base-case assumptions. Compare with the current price to judge cheapness.",
    "mos":           "Margin of Safety — how far below intrinsic value the stock trades. >20% = BUY zone; negative = trading above fair value.",
    "signal":        "YieldIQ's investment signal derived from Margin of Safety, quality scores (Moat, Piotroski, Earnings Quality) and recent insider activity.",
    # DCF inputs
    "wacc":          "Weighted Average Cost of Capital — the hurdle rate used to discount future cash flows. Lower WACC → higher valuation; sensitive to interest rates.",
    "terminal_g":    "Terminal Growth Rate — the perpetual annual growth assumed after the explicit forecast period ends. Typically 2–4% for mature companies.",
    "fcf_growth":    "Free Cash Flow growth rate used in the DCF model, derived from historical FCF trend and analyst estimates.",
    "forecast_yrs":  "Number of years explicitly modelled before switching to terminal value. 5–10 years is standard.",
    # Quality
    "moat":          "Economic Moat: the competitive advantage protecting future cash flows. Wide > Narrow > None; wider moats justify lower required MoS.",
    "piotroski":     "Piotroski F-Score (0–9): composite of 9 accounting signals measuring financial strength. ≥7 = strong; ≤3 = weak.",
    "eq_grade":      "Earnings Quality Grade (A–F): 9-factor composite measuring how reliable and sustainable the reported earnings are.",
    "beat_rate":     "% of the last 8 quarters where actual EPS beat analyst consensus. >75% = consistent outperformer.",
    # Market / risk
    "beta":          "Beta: how much the stock moves relative to the broader market. Beta 1.5 = 50% more volatile than the index.",
    "pe":            "Price-to-Earnings ratio. Compare within sector — a P/E of 25 may be cheap for high-growth and expensive for a utility.",
    "roe":           "Return on Equity — net income as % of shareholders' equity. Measures how efficiently management uses investor capital.",
    "de_ratio":      "Debt-to-Equity ratio. Higher D/E = more financial leverage; increases both risk and potential return.",
    # Smart money
    "insider_sent":  "Insider Sentiment: derived from net share purchases by executives/directors in the last 90 days. Insiders buying = bullish signal.",
    "inst_pct":      "Institutional ownership % — share of float held by funds, ETFs, pension funds. High % signals professional investor conviction.",
    # Trade plan
    "buy_price":     "Maximum price at which to start a position while maintaining adequate margin of safety.",
    "target_price":  "Price target derived from bear/base/bull scenario analysis — the base-case intrinsic value.",
    "stop_loss":     "Recommended stop-loss level to limit downside if the investment thesis fails.",
    "rr_ratio":      "Risk/Reward ratio = upside to target ÷ downside to stop-loss. Aim for ≥ 2.0 before entering a position.",
    # Scenarios
    "scenarios":     "Bear / Base / Bull scenarios stress-test the DCF with different growth and margin assumptions to bound the range of fair values.",
    "sensitivity":   "Sensitivity table: how intrinsic value changes across different WACC (±1%) and terminal growth (±0.5%) combinations.",
}


def tooltip(key: str) -> str:
    """Return a help-text string for Streamlit widget help= parameter."""
    return METRIC_TOOLTIPS.get(key, "")


def show_tooltips() -> bool:
    """
    True when the current user hasn't completed onboarding yet.
    Use this to conditionally pass help= to st.metric / st.number_input.
    """
    if st.session_state.get(_DONE_KEY):
        return False
    email = st.session_state.get("auth_email", "")
    if not email or email == "guest":
        return False
    return not is_onboarding_completed(email)


# ════════════════════════════════════════════════════════════════
# STEP CONTENT
# ════════════════════════════════════════════════════════════════

def _render_progress(step: int) -> None:
    """Render the progress bar + step label at the top of the wizard."""
    pct = (step - 1) / (_TOTAL_STEPS - 1)  # 0.0 → 0.5 → 1.0
    st.progress(pct)
    dots = []
    for i in range(1, _TOTAL_STEPS + 1):
        if i < step:
            dots.append(
                '<span style="display:inline-block;width:8px;height:8px;'
                'background:#1D4ED8;border-radius:50%;margin:0 4px;opacity:0.7;"></span>'
            )
        elif i == step:
            dots.append(
                '<span style="display:inline-block;width:24px;height:8px;'
                'background:linear-gradient(90deg,#1D4ED8,#06B6D4);'
                'border-radius:4px;margin:0 4px;"></span>'
            )
        else:
            dots.append(
                '<span style="display:inline-block;width:8px;height:8px;'
                'background:rgba(30,58,138,0.15);border-radius:50%;margin:0 4px;"></span>'
            )
    st.html(
        '<div style="text-align:center;margin:8px 0 20px;">'
        + "".join(dots)
        + f'<div style="font-size:10px;color:#6B7280;margin-top:8px;'
          f'letter-spacing:0.10em;font-weight:600;">STEP {step} OF {_TOTAL_STEPS}</div>'
          f'</div>'
    )


def _step1() -> None:
    """Step 1 — Welcome to YieldIQ."""
    # Hero banner
    st.html("""
    <div style="background:linear-gradient(135deg,#1E3A8A 0%,#1D4ED8 60%,#0369A1 100%);
                border-radius:16px;padding:32px 28px;text-align:center;
                margin-bottom:20px;position:relative;overflow:hidden;">
      <div style="position:absolute;top:-30px;right:-30px;width:120px;height:120px;
                  background:rgba(255,255,255,0.06);border-radius:50%;"></div>
      <div style="position:absolute;bottom:-20px;left:-20px;width:80px;height:80px;
                  background:rgba(255,255,255,0.04);border-radius:50%;"></div>
      <div style="font-size:44px;margin-bottom:14px;position:relative;">📊</div>
      <div style="font-size:24px;font-weight:800;color:#FFFFFF;
                  font-family:Inter,sans-serif;letter-spacing:-0.01em;
                  margin-bottom:8px;position:relative;">
        Welcome to YieldIQ
      </div>
      <div style="font-size:13px;color:rgba(255,255,255,0.80);
                  max-width:380px;margin:0 auto;line-height:1.7;position:relative;">
        Professional DCF valuation and stock analysis — built for investors who think
        in terms of <strong style="color:#BAE6FD;">intrinsic value</strong>, not price momentum.
      </div>
    </div>
    """)

    # What YieldIQ does — 3 feature tiles
    c1, c2, c3 = st.columns(3)
    _tile_css = (
        "border-radius:12px;padding:18px 14px;text-align:center;"
        "border:1px solid;height:100%;"
    )
    with c1:
        st.html(
            f'<div style="{_tile_css}background:#EFF6FF;border-color:#BFDBFE;">'
            '<div style="font-size:28px;margin-bottom:8px;">🔍</div>'
            '<div style="font-size:12px;font-weight:700;color:#1D4ED8;margin-bottom:6px;">DCF Valuation</div>'
            '<div style="font-size:11px;color:#4B5563;line-height:1.5;">'
            'Multi-year FCF model with WACC, terminal value &amp; scenario stress-tests</div>'
            '</div>'
        )
    with c2:
        st.html(
            f'<div style="{_tile_css}background:#F0FDF4;border-color:#BBF7D0;">'
            '<div style="font-size:28px;margin-bottom:8px;">🏆</div>'
            '<div style="font-size:12px;font-weight:700;color:#059669;margin-bottom:6px;">Quality Scores</div>'
            '<div style="font-size:11px;color:#4B5563;line-height:1.5;">'
            'Moat analysis, Piotroski F-Score &amp; earnings quality — know what you own</div>'
            '</div>'
        )
    with c3:
        st.html(
            f'<div style="{_tile_css}background:#F5F3FF;border-color:#DDD6FE;">'
            '<div style="font-size:28px;margin-bottom:8px;">🤖</div>'
            '<div style="font-size:12px;font-weight:700;color:#7C3AED;margin-bottom:6px;">AI Analyst</div>'
            '<div style="font-size:11px;color:#4B5563;line-height:1.5;">'
            'Ask plain-English questions about any stock — powered by AI</div>'
            '</div>'
        )

    st.html('<div style="height:16px;"></div>')

    # Mock analysis preview — static HTML showing what output looks like
    st.html("""
    <div style="background:#F8FAFC;border:1.5px solid #E2E8F0;border-radius:14px;
                padding:0;overflow:hidden;margin-top:4px;">
      <div style="background:linear-gradient(90deg,#1E3A8A,#1D4ED8);
                  padding:10px 18px;display:flex;align-items:center;
                  justify-content:space-between;">
        <div style="font-size:13px;font-weight:700;color:#FFFFFF;">
          Apple Inc. · AAPL
        </div>
        <div style="background:#059669;color:#FFFFFF;font-size:11px;
                    font-weight:800;padding:3px 14px;border-radius:100px;">
          BUY
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;
                  gap:0;padding:16px 18px;">
        <div style="text-align:center;padding:0 8px;
                    border-right:1px solid #E5E7EB;">
          <div style="font-size:10px;color:#9CA3AF;margin-bottom:4px;
                      text-transform:uppercase;letter-spacing:0.05em;">Price</div>
          <div style="font-size:18px;font-weight:800;color:#111827;
                      font-family:'IBM Plex Mono',monospace;">$213</div>
        </div>
        <div style="text-align:center;padding:0 8px;
                    border-right:1px solid #E5E7EB;">
          <div style="font-size:10px;color:#9CA3AF;margin-bottom:4px;
                      text-transform:uppercase;letter-spacing:0.05em;">Intrinsic Value</div>
          <div style="font-size:18px;font-weight:800;color:#1D4ED8;
                      font-family:'IBM Plex Mono',monospace;">$268</div>
        </div>
        <div style="text-align:center;padding:0 8px;
                    border-right:1px solid #E5E7EB;">
          <div style="font-size:10px;color:#9CA3AF;margin-bottom:4px;
                      text-transform:uppercase;letter-spacing:0.05em;">Margin of Safety</div>
          <div style="font-size:18px;font-weight:800;color:#059669;
                      font-family:'IBM Plex Mono',monospace;">+20.5%</div>
        </div>
        <div style="text-align:center;padding:0 8px;">
          <div style="font-size:10px;color:#9CA3AF;margin-bottom:4px;
                      text-transform:uppercase;letter-spacing:0.05em;">Moat</div>
          <div style="font-size:18px;font-weight:800;color:#D97706;
                      font-family:'IBM Plex Mono',monospace;">Wide</div>
        </div>
      </div>
      <div style="padding:8px 18px 14px;font-size:11px;color:#9CA3AF;
                  text-align:center;font-style:italic;">
        Example analysis output · Your results will use live market data
      </div>
    </div>
    """)


def _step2() -> None:
    """Step 2 — Try It: Analyse a Stock."""
    st.html("""
    <div style="margin-bottom:20px;">
      <div style="font-size:22px;font-weight:800;color:#111827;
                  font-family:Inter,sans-serif;letter-spacing:-0.01em;
                  margin-bottom:8px;">Try It: Analyse a Stock</div>
      <div style="font-size:14px;color:#6B7280;line-height:1.6;">
        Enter any US ticker below to run your first full DCF analysis.
        We've pre-filled <strong style="color:#1D4ED8;">Apple (AAPL)</strong> to get you started.
      </div>
    </div>
    """)

    # Ticker input
    st.html("""
    <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:6px;">
      Ticker symbol
    </div>
    """)
    ticker_val = st.text_input(
        "Ticker",
        value="AAPL",
        placeholder="e.g. AAPL, MSFT, GOOGL",
        label_visibility="collapsed",
        key="ob_ticker_input",
    ).strip().upper()

    st.html("""
    <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:10px;
                padding:10px 14px;margin:12px 0 20px;font-size:12px;color:#92400E;
                display:flex;align-items:flex-start;gap:8px;">
      <span style="font-size:14px;flex-shrink:0;">💡</span>
      <span>
        US stocks: <code style="background:#FEF3C7;padding:1px 5px;border-radius:3px;">AAPL</code>,
        <code style="background:#FEF3C7;padding:1px 5px;border-radius:3px;">MSFT</code> &nbsp;·&nbsp;
        Indian stocks: add <code style="background:#FEF3C7;padding:1px 5px;border-radius:3px;">.NS</code>
        suffix, e.g. <code style="background:#FEF3C7;padding:1px 5px;border-radius:3px;">RELIANCE.NS</code>
      </span>
    </div>
    """)

    # What happens next
    st.html("""
    <div style="font-size:12px;font-weight:700;color:#374151;
                margin-bottom:10px;letter-spacing:0.04em;text-transform:uppercase;">
      What happens when you click Run Analysis:
    </div>
    """)
    for num, text in [
        ("1", "YieldIQ fetches 5 years of financial data from Yahoo Finance"),
        ("2", "The DCF model runs with AI-calibrated growth estimates"),
        ("3", "Your full analysis dashboard appears — signal, IV, scenarios and more"),
    ]:
        st.html(
            f'<div style="display:flex;align-items:flex-start;gap:12px;'
            f'padding:9px 14px;background:#F9FAFB;border:1px solid #E5E7EB;'
            f'border-radius:9px;margin-bottom:6px;">'
            f'<div style="width:22px;height:22px;background:#1D4ED8;color:#FFFFFF;'
            f'border-radius:50%;display:flex;align-items:center;justify-content:center;'
            f'font-size:11px;font-weight:700;flex-shrink:0;">{num}</div>'
            f'<div style="font-size:12.5px;color:#374151;line-height:1.5;'
            f'padding-top:2px;">{text}</div>'
            f'</div>'
        )

    st.html('<div style="height:4px;"></div>')
    return ticker_val  # returned so wizard can read it


def _step3() -> None:
    """Step 3 — You're all set!"""
    st.balloons()

    st.html("""
    <div style="text-align:center;margin-bottom:28px;">
      <div style="font-size:52px;margin-bottom:14px;">🎉</div>
      <div style="font-size:26px;font-weight:800;color:#111827;
                  font-family:Inter,sans-serif;letter-spacing:-0.01em;
                  margin-bottom:10px;">You're all set!</div>
      <div style="font-size:14px;color:#6B7280;max-width:380px;
                  margin:0 auto;line-height:1.7;">
        Your YieldIQ account is ready. Here's everything waiting for you:
      </div>
    </div>
    """)

    capabilities = [
        ("📊", "#1D4ED8", "#EFF6FF", "#BFDBFE",
         "Stock Analysis",
         "Full DCF valuation · Bear/Base/Bull scenarios · Sensitivity heatmap · Monte Carlo simulation"),
        ("🏆", "#059669", "#F0FDF4", "#BBF7D0",
         "Quality Scoring",
         "Economic Moat · Piotroski F-Score · Earnings Quality · Insider activity tracker"),
        ("🔭", "#7C3AED", "#F5F3FF", "#DDD6FE",
         "Screener &amp; Sector View",
         "Filter S&amp;P 1500 by signal · Sector treemap · Top opportunities dashboard"),
        ("💼", "#D97706", "#FFFBEB", "#FDE68A",
         "Portfolio &amp; Watchlist",
         "Log trades · Track P&amp;L · Price alerts · Google Sheets sync"),
    ]

    for icon, fg, bg, border, title, body in capabilities:
        st.html(
            f'<div style="display:flex;align-items:flex-start;gap:14px;'
            f'background:{bg};border:1px solid {border};border-radius:12px;'
            f'padding:14px 18px;margin-bottom:8px;">'
            f'<div style="width:38px;height:38px;background:white;border-radius:9px;'
            f'border:1px solid {border};display:flex;align-items:center;'
            f'justify-content:center;font-size:20px;flex-shrink:0;">{icon}</div>'
            f'<div>'
            f'<div style="font-size:13px;font-weight:700;color:{fg};margin-bottom:4px;">{title}</div>'
            f'<div style="font-size:12px;color:#4B5563;line-height:1.5;">{body}</div>'
            f'</div></div>'
        )

    st.html("""
    <div style="background:linear-gradient(135deg,#F0F9FF,#EFF6FF);
                border:1px solid #BAE6FD;border-radius:12px;
                padding:14px 18px;margin-top:8px;text-align:center;
                font-size:13px;color:#0369A1;line-height:1.6;">
      <strong>Free plan:</strong> 5 analyses per day · Upgrade anytime for unlimited access
    </div>
    """)


# ════════════════════════════════════════════════════════════════
# WIZARD SHELL
# ════════════════════════════════════════════════════════════════

def _onboarding_dialog() -> None:
    """3-step onboarding wizard rendered inline."""
    email = st.session_state.get("auth_email", "")
    step  = st.session_state.get(_STEP_KEY, 1)

    # Wizard card styling
    st.html("""
    <style>
    /* Onboarding wizard: style the container border */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 18px !important;
        border: 1.5px solid #E0E7FF !important;
        box-shadow: 0 8px 32px rgba(29,78,216,0.10) !important;
        overflow: hidden !important;
    }
    </style>
    """)

    with st.container(border=True):
        # ── Progress bar + step counter ────────────────────────────
        _render_progress(step)

        # ── Step content ───────────────────────────────────────────
        _step2_ticker = None
        if step == 1:
            _step1()
        elif step == 2:
            _step2_ticker = _step2()
        elif step == 3:
            _step3()

        st.html('<div style="height:16px;"></div>')

        # ── Navigation ─────────────────────────────────────────────
        if step == 1:
            nav_cols = st.columns([1, 3])
            with nav_cols[0]:
                if st.button("Skip tour", type="secondary",
                             use_container_width=True, key="ob_skip"):
                    st.session_state[_SHOW_KEY] = False
                    st.rerun()
            with nav_cols[1]:
                if st.button("Let's analyse your first stock →",
                             type="primary", use_container_width=True,
                             key="ob_next_1"):
                    st.session_state[_STEP_KEY] = 2
                    if email and email != "guest":
                        _save_progress(email, 2)
                    st.rerun()

        elif step == 2:
            nav_cols = st.columns([1, 2, 1])
            with nav_cols[0]:
                if st.button("← Back", type="secondary",
                             use_container_width=True, key="ob_back_2"):
                    st.session_state[_STEP_KEY] = 1
                    if email and email != "guest":
                        _save_progress(email, 1)
                    st.rerun()
            with nav_cols[1]:
                if st.button("Run Analysis",
                             type="primary", use_container_width=True,
                             key="ob_run"):
                    ticker = st.session_state.get("ob_ticker_input", "AAPL").strip().upper() or "AAPL"
                    st.session_state["_prefill_ticker"] = ticker
                    st.session_state["_auto_analyse"]   = True
                    # Advance to step 3 (completion) first
                    st.session_state[_STEP_KEY] = 3
                    if email and email != "guest":
                        _save_progress(email, 3)
                    st.rerun()
            with nav_cols[2]:
                if st.button("Skip", type="secondary",
                             use_container_width=True, key="ob_skip_2"):
                    st.session_state[_STEP_KEY] = 3
                    if email and email != "guest":
                        _save_progress(email, 3)
                    st.rerun()

        elif step == 3:
            nav_cols = st.columns([1, 2])
            with nav_cols[0]:
                if st.button("← Back", type="secondary",
                             use_container_width=True, key="ob_back_3"):
                    st.session_state[_STEP_KEY] = 2
                    if email and email != "guest":
                        _save_progress(email, 2)
                    st.rerun()
            with nav_cols[1]:
                if st.button("Go to Dashboard →",
                             type="primary", use_container_width=True,
                             key="ob_done"):
                    if email and email != "guest":
                        mark_onboarding_completed(email)
                    else:
                        st.session_state[_DONE_KEY] = True
                        st.session_state[_SHOW_KEY] = False
                    st.rerun()


# ════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINTS (called from app.py)
# ════════════════════════════════════════════════════════════════

def maybe_show_wizard() -> None:
    """
    Call once per Streamlit run in the main app body (after init_tier).
    Auto-shows the wizard on first session for users who haven't completed it.
    Subsequent renders only show it when _SHOW_KEY is True (resume button).
    """
    email = st.session_state.get("auth_email", "")

    # Don't show for guests / unauthenticated
    if not email or email == "guest":
        return

    # Already finished onboarding this session → skip DB check
    if st.session_state.get(_DONE_KEY):
        return

    # First run of this session → check DB and auto-show if needed
    if not st.session_state.get(_INIT_KEY):
        st.session_state[_INIT_KEY] = True
        completed = is_onboarding_completed(email)
        if completed:
            st.session_state[_DONE_KEY] = True
            return
        # Restore last saved step so user doesn't restart from step 1
        saved_step = _get_last_step(email)
        st.session_state.setdefault(_STEP_KEY, max(1, min(saved_step, _TOTAL_STEPS)))
        # Auto-show on fresh login
        st.session_state[_SHOW_KEY] = True

    # Open dialog if flag is set
    if st.session_state.get(_SHOW_KEY):
        _onboarding_dialog()


def render_resume_button() -> None:
    """
    Render a 'Resume Tutorial' button in the sidebar.
    Only visible when the user is logged in, onboarding is incomplete,
    and the wizard is currently dismissed.
    """
    email = st.session_state.get("auth_email", "")
    if not email or email == "guest":
        return
    if st.session_state.get(_DONE_KEY):
        return
    if st.session_state.get(_SHOW_KEY):
        return  # wizard already open

    # Don't hit DB every render — use cached session flag
    if not st.session_state.get(_INIT_KEY):
        return  # maybe_show_wizard not yet called

    step  = st.session_state.get(_STEP_KEY, 1)
    label = f"▶ Resume Tutorial (Step {step}/{_TOTAL_STEPS})"
    if st.button(label, use_container_width=True, key="ob_resume_sidebar"):
        st.session_state[_SHOW_KEY] = True
        st.rerun()
