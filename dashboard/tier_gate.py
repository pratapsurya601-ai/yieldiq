# dashboard/tier_gate.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — Tier Gating System  (SQLite backend)
# Public API identical to original — app.py needs ZERO changes.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import os
import sqlite3
import threading
import json as _json
from datetime import date, datetime, timedelta
from pathlib import Path
import streamlit as st

# ── Launch-region guard ────────────────────────────────────────
try:
    from utils.config import LAUNCH_REGION as _LAUNCH_REGION
except Exception:
    _LAUNCH_REGION = "US"   # safe default

import importlib.util as _ilu
_auth_path = Path(__file__).parent / "auth.py"
_auth_spec = _ilu.spec_from_file_location("auth", _auth_path)
_auth_mod  = _ilu.module_from_spec(_auth_spec)
_auth_spec.loader.exec_module(_auth_mod)
_init_auth_db     = _auth_mod.init_auth_db
_login_user       = _auth_mod.login_user
_register_user    = _auth_mod.register_user
_reset_password   = _auth_mod.reset_password
_validate_session = _auth_mod.validate_session
_logout_session   = _auth_mod.logout_session
_init_auth_db()

LIMITS = {
    "free": {
        "analyses_per_day": 5,          "reports_per_month": 0,
        "report_cost": 14.99,           "screener_per_week": 0,
        "watchlist_stocks": 10,         "india_access": False,
        "europe_access": False,         "action_plan": False,
        "quality_score": False,         "scenarios": False,
        "sensitivity": False,           "monte_carlo": False,
        "portfolio": False,             "compare_stocks": False,
        "api_calls_per_day": 0,         "simple_mode_only": True,
        "pdf_reports_per_month": 0,     "pdf_report_cost": 4.99,
        "sheets_sync": False,           "ai_questions_per_day": 5,
        "excel_export": False,          "bulk_screener": False,
    },
    "starter": {
        "analyses_per_day": 50,         "reports_per_month": 5,
        "report_cost": 0,               "screener_per_week": 9999,
        "watchlist_stocks": 50,         "india_access": False,
        "europe_access": False,         "action_plan": True,
        "quality_score": True,          "scenarios": True,
        "sensitivity": True,            "monte_carlo": False,
        "portfolio": True,              "compare_stocks": True,
        "api_calls_per_day": 0,         "simple_mode_only": False,
        "pdf_reports_per_month": 5,     "pdf_report_cost": 0,
        "sheets_sync": True,            "ai_questions_per_day": 50,
        "excel_export": True,           "bulk_screener": False,
    },
    "pro": {
        "analyses_per_day": 9999,       "reports_per_month": 9999,
        "report_cost": 0,               "screener_per_week": 9999,
        "watchlist_stocks": 9999,       "india_access": True,
        "europe_access": True,          "action_plan": True,
        "quality_score": True,          "scenarios": True,
        "sensitivity": True,            "monte_carlo": True,
        "portfolio": True,              "compare_stocks": True,
        "api_calls_per_day": 500,       "simple_mode_only": False,
        "pdf_reports_per_month": 9999,  "pdf_report_cost": 0,
        "sheets_sync": True,            "ai_questions_per_day": 9999,
        "excel_export": True,           "bulk_screener": True,
    },
}

# Keep "premium" as a backwards-compat alias for "starter"
LIMITS["premium"] = LIMITS["starter"]

_ANALYTICS_DB = Path(__file__).parent / "analytics.db"
_nudge_lock   = threading.Lock()

# ── Nudge tracking ─────────────────────────────────────────────

def _init_nudge_table() -> None:
    try:
        with _nudge_lock:
            con = sqlite3.connect(_ANALYTICS_DB)
            con.execute("""CREATE TABLE IF NOT EXISTS nudge_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT,
                tier       TEXT,
                nudge_type TEXT,
                action     TEXT,
                ts         TEXT DEFAULT (datetime('now'))
            )""")
            con.commit(); con.close()
    except Exception:
        pass

def _track_nudge(user_email: str, tier_name: str, nudge_type: str, action: str = "shown") -> None:
    """Fire-and-forget — never raises."""
    try:
        _init_nudge_table()
        with _nudge_lock:
            con = sqlite3.connect(_ANALYTICS_DB)
            con.execute(
                "INSERT INTO nudge_log (user_email, tier, nudge_type, action) VALUES (?,?,?,?)",
                (user_email, tier_name, nudge_type, action),
            )
            con.commit(); con.close()
    except Exception:
        pass


WEBSITE_URL = os.environ.get("YIELDIQ_WEBSITE_URL", "https://www.yieldiq.in")
PRICING_URL = WEBSITE_URL + "/pricing.html"
# In-app upgrade: navigate to the pricing tab via query param
UPGRADE_URL = PRICING_URL
TIER_NAMES  = {"free": "Free", "starter": "Starter", "premium": "Starter", "pro": "Pro"}
TIER_COLORS = {"free": "#6B7280", "starter": "#1D4ED8", "premium": "#1D4ED8", "pro": "#059669"}

# Pricing constants — single source of truth
_STARTER_MONTHLY  = "$29/mo"
_STARTER_ANNUAL   = "$23/mo"   # ~20% off ($276/yr)
_PRO_MONTHLY      = "$79/mo"
_PRO_ANNUAL       = "$63/mo"   # ~20% off ($756/yr)
_SESSION_KEY      = "yiq_session_token"


# ══════════════════════════════════════════════════════════════
# SESSION / TOKEN HELPERS  (unchanged)
# ══════════════════════════════════════════════════════════════

def _get_stored_token():
    if st.session_state.get(_SESSION_KEY): return st.session_state[_SESSION_KEY]
    try:
        t = st.query_params.get("token", "")
        if t: return t
    except Exception: pass
    return ""

def _save_token(token):
    st.session_state[_SESSION_KEY] = token
    try: st.query_params["token"] = token
    except Exception: pass

def _clear_token():
    st.session_state.pop(_SESSION_KEY, None); st.session_state.pop("tier", None)
    st.session_state.pop("auth_email", None)
    try:
        if "token" in st.query_params: del st.query_params["token"]
    except Exception: pass

def _init_usage_counters():
    today = str(date.today()); month = datetime.now().strftime("%Y-%m")
    week  = datetime.now().strftime("%Y-W%W")
    if st.session_state.get("usage_date") != today:
        st.session_state["usage_date"]     = today
        st.session_state["analyses_today"] = 0
    if st.session_state.get("usage_month") != month:
        st.session_state["usage_month"]       = month
        st.session_state["reports_month"]     = 0
        st.session_state["pdf_reports_month"] = 0
    if st.session_state.get("usage_week") != week:
        st.session_state["usage_week"]    = week
        st.session_state["screener_week"] = 0
    try:
        if st.query_params.get("signout") == "1":
            token = _get_stored_token()
            if token and token != "_guest_": _logout_session(token)
            _clear_token(); st.rerun()
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# LOGIN CARD  (unchanged logic, keeps existing tab-based flow)
# ══════════════════════════════════════════════════════════════

def _render_login_card():
    # CSS targeting Streamlit elements must use st.markdown(), not st.html()
    st.markdown("""<style>
.yiq-aw{max-width:420px;margin:60px auto 0;font-family:'Inter',sans-serif}
.yiq-ac{background:#fff;border:1px solid #E2E8F0;border-radius:16px;
        padding:36px 32px 28px;box-shadow:0 4px 24px rgba(15,23,42,.08)}
details summary svg,details>summary>svg,
[data-testid="stExpander"] summary svg,[data-testid="stTabs"] button svg,
.streamlit-expanderHeader svg,button[aria-expanded] svg{
  display:none!important;width:0!important;height:0!important;
  font-size:0!important;opacity:0!important;visibility:hidden!important;
  position:absolute!important;clip:rect(0,0,0,0)!important;color:transparent!important}
</style>""", unsafe_allow_html=True)
    st.html("""<script>
(function(){
  // Minimal: only hide SVGs in summaries on the login page
  function clean(){
    document.querySelectorAll('summary svg').forEach(function(s){s.style.display='none';});
    document.querySelectorAll('summary').forEach(function(el){
      el.childNodes.forEach(function(n){
        if(n.nodeType===3){var t=(n.textContent||'').trim();
          if(t==="_arrow_right"||t.startsWith("_arrow")||t.startsWith("_expand")||
             t.startsWith("keyboard_")||/^_[a-z][a-z_]+$/.test(t)){n.textContent='';}}
      });
    });
  }
  clean();
  [100,500,1500].forEach(function(ms){setTimeout(clean,ms);});
})();
</script>
<div class="yiq-aw"><div class="yiq-ac">
<div style="text-align:center;margin-bottom:20px;">
  <div style="width:48px;height:48px;background:linear-gradient(135deg,#1D4ED8,#06B6D4);
              border-radius:12px;display:inline-flex;align-items:center;
              justify-content:center;font-size:24px;margin-bottom:8px;">📈</div>
  <div style="font-size:22px;font-weight:700;color:#0F172A;">YieldIQ</div>
  <div style="font-size:13px;color:#64748B;margin-top:4px;">Institutional DCF Analysis</div>
</div>""")

    l_tab, r_tab, fp_tab, f_tab = st.tabs(["  Sign in  ", "  Create account  ", "  Reset password  ", "  Continue free  "])

    with l_tab:
        with st.form("_yiq_login"):
            em = st.text_input("Email", placeholder="you@example.com")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in →", width='stretch', type="primary"):
                if not em or not pw: st.error("Enter email and password.")
                else:
                    with st.spinner("Signing in…"):
                        res = _login_user(em, pw)
                    if res["ok"]:
                        _save_token(res["token"])
                        st.session_state["tier"]       = res["tier"]
                        st.session_state["auth_email"] = res["email"]
                        _init_usage_counters(); st.rerun()
                    else: st.error(res["error"])

    with r_tab:
        with st.form("_yiq_register"):
            re  = st.text_input("Email",               key="_re")
            rp1 = st.text_input("Password (8+ chars)", key="_rp1", type="password")
            rp2 = st.text_input("Confirm password",    key="_rp2", type="password")
            if st.form_submit_button("Create free account →", width='stretch', type="primary"):
                if not re or not rp1:   st.error("Fill in all fields.")
                elif rp1 != rp2:        st.error("Passwords don't match.")
                elif len(rp1) < 8:      st.error("Password must be 8+ characters.")
                else:
                    res = _register_user(re, rp1, "free")
                    if res["ok"]:
                        lr = _login_user(re, rp1)
                        if lr["ok"]:
                            _save_token(lr["token"])
                            st.session_state["tier"]       = "free"
                            st.session_state["auth_email"] = re
                            _init_usage_counters(); st.rerun()
                    else: st.error(res["error"])

    with fp_tab:
        with st.form("_yiq_reset_pw"):
            rpe = st.text_input("Email", placeholder="you@example.com", key="_rpe")
            rpn1 = st.text_input("New password (8+ chars)", type="password", key="_rpn1")
            rpn2 = st.text_input("Confirm new password", type="password", key="_rpn2")
            if st.form_submit_button("Reset password →", width='stretch', type="primary"):
                if not rpe or not rpn1:
                    st.error("Fill in all fields.")
                elif rpn1 != rpn2:
                    st.error("Passwords don't match.")
                elif len(rpn1) < 8:
                    st.error("Password must be 8+ characters.")
                else:
                    res = _reset_password(rpe, rpn1)
                    if res["ok"]:
                        st.success("✅ Password reset! You can now sign in with your new password.")
                    else:
                        st.error(res["error"])

    with f_tab:
        st.markdown("**5 free analyses per day, no account required.**")
        if st.button("Continue as Free →", width='stretch'):
            st.session_state["tier"]       = "free"
            st.session_state["auth_email"] = "guest"
            st.session_state[_SESSION_KEY] = "_guest_"
            _init_usage_counters(); st.rerun()

    st.html("""<div style="font-size:11px;color:#94A3B8;text-align:center;
margin-top:16px;line-height:1.6;">For informational purposes only.
Not investment advice. YieldIQ is not a registered investment adviser.
</div></div></div>""")
    st.stop()


# ══════════════════════════════════════════════════════════════
# PUBLIC TIER API  (all unchanged)
# ══════════════════════════════════════════════════════════════

def init_tier():
    # Handle Razorpay payment callback (if returning from checkout)
    _handle_payment_callback()

    if os.environ.get("YIELDIQ_ADMIN") == "1":
        st.session_state["tier"] = "pro"; st.session_state["auth_email"] = "admin"
        _init_usage_counters(); return
    stored = _get_stored_token()
    if stored == "_guest_":
        st.session_state.setdefault("tier", "free"); _init_usage_counters(); return
    if st.session_state.get("tier") and st.session_state.get(_SESSION_KEY):
        _init_usage_counters(); return
    if stored:
        session = _validate_session(stored)
        if session:
            _save_token(stored); st.session_state["tier"] = session["tier"]
            st.session_state["auth_email"] = session["email"]
            _init_usage_counters(); return
        _clear_token()
    _render_login_card()


def tier()        -> str:
    t = st.session_state.get("tier", "free")
    return "starter" if t == "premium" else t
def is_free()     -> bool: return tier() == "free"
def is_starter()  -> bool: return tier() == "starter"
def is_premium()  -> bool: return tier() in ("starter", "pro")
def is_pro()      -> bool: return tier() == "pro"
def limit(key):            return LIMITS[tier()].get(key)
def can(feature)  -> bool: return bool(LIMITS[tier()].get(feature, False))

def can_analyse()     -> bool: return st.session_state.get("analyses_today", 0) < LIMITS[tier()]["analyses_per_day"]
def record_analysis() -> None: st.session_state["analyses_today"] = st.session_state.get("analyses_today", 0) + 1

def can_download_report():
    used, lim, cost = st.session_state.get("reports_month", 0), LIMITS[tier()]["reports_per_month"], LIMITS[tier()]["report_cost"]
    if lim == 0:    return False, f"Buy for ${cost:.2f}"
    if used >= lim: return False, f"Monthly limit reached — buy extra for ${cost:.2f}"
    return True, f"{lim - used} remaining this month"

def record_report() -> None: st.session_state["reports_month"] = st.session_state.get("reports_month", 0) + 1

def can_download_pdf():
    used = st.session_state.get("pdf_reports_month", 0)
    lim  = LIMITS[tier()].get("pdf_reports_per_month", 0)
    cost = LIMITS[tier()].get("pdf_report_cost", 4.99)
    if lim == 0:    return False, f"Buy for ${cost:.2f}"
    if lim >= 9999: return True,  "Unlimited (Pro)"
    if used >= lim: return False, f"Monthly PDF limit reached — buy extra for ${cost:.2f}"
    return True, f"{lim - used} PDF report(s) remaining this month"

def record_pdf_report() -> None:
    st.session_state["pdf_reports_month"] = st.session_state.get("pdf_reports_month", 0) + 1

def can_run_screener():
    used, lim = st.session_state.get("screener_week", 0), LIMITS[tier()]["screener_per_week"]
    if lim == 0:           return False, "Upgrade to Starter to run the screener"
    if used >= lim < 9999: return False, "Weekly screen used — resets Monday"
    return True, ""

def record_screener() -> None: st.session_state["screener_week"] = st.session_state.get("screener_week", 0) + 1

def check_ticker_allowed(ticker: str):
    t = ticker.upper()
    if _LAUNCH_REGION == "US":
        if t.endswith(".NS") or t.endswith(".BO"):
            return False, "india_region"
        if any(t.endswith(s) for s in (".DE", ".L", ".PA", ".AS", ".SW")):
            return False, "europe_region"
        return True, ""
    if (t.endswith(".NS") or t.endswith(".BO")) and not limit("india_access"):
        return False, "india"
    if any(t.endswith(s) for s in (".DE", ".L", ".PA", ".AS", ".SW")) and not limit("europe_access"):
        return False, "europe"
    return True, ""


# ══════════════════════════════════════════════════════════════
# UPGRADE COPY — per-feature text  (updated prices + benefit line)
# ══════════════════════════════════════════════════════════════

UPGRADE_COPY = {
    "analyses":      {"emoji": "🔍", "title": "Daily limit reached",         "benefit": "run up to 50 analyses per day",                            "desc": "5 free analyses/day — upgrade for up to 50 (Starter) or unlimited (Pro).",        "cta": "Upgrade to Starter"},
    "action_plan":   {"emoji": "📋", "title": "Model-generated analysis",     "benefit": "see DCF price levels and risk ranges",                      "desc": "DCF discount threshold, model fair value estimate, risk range.",                   "cta": "Upgrade to Starter"},
    "quality_score": {"emoji": "⭐", "title": "Business quality score",       "benefit": "see the 8-factor quality grade",                            "desc": "8-factor grade — growth, margins, debt, FCF.",                                    "cta": "Upgrade to Starter"},
    "scenarios":     {"emoji": "🐻", "title": "Bear/Base/Bull scenarios",     "benefit": "stress-test across growth and discount assumptions",         "desc": "3-scenario DCF across growth & discount assumptions.",                            "cta": "Upgrade to Starter"},
    "sensitivity":   {"emoji": "🗂",  "title": "Sensitivity analysis",         "benefit": "see how IV changes with WACC and growth",                   "desc": "Fair value vs WACC and growth assumptions.",                                      "cta": "Upgrade to Starter"},
    "monte_carlo":   {"emoji": "🎲", "title": "Monte Carlo simulation",       "benefit": "see probability distributions across 1,000 scenarios",      "desc": "1,000 scenarios showing probability of outcomes.",                                "cta": "Upgrade to Pro"},
    "screener":      {"emoji": "📊", "title": "Stock screener",               "benefit": "screen 1,500 S&P stocks for undervalued names",              "desc": "Find undervalued stocks across the S&P 1500.",                                    "cta": "Upgrade to Starter"},
    "excel":         {"emoji": "📄", "title": "Excel model download",         "benefit": "download the full DCF model in Excel",                       "desc": "DCF, scenarios, WACC build-up in Excel.",                                        "cta": "Upgrade to Starter"},
    "excel_export":  {"emoji": "📄", "title": "Excel model download",         "benefit": "download the full DCF model in Excel",                       "desc": "DCF, scenarios, WACC build-up in Excel.",                                        "cta": "Upgrade to Starter"},
    "pdf_report":    {"emoji": "📑", "title": "PDF report",                   "benefit": "download institutional-quality PDF reports",                 "desc": "Institutional PDF: DCF · Quality · Model Signals.",                              "cta": "Upgrade to Starter"},
    "sheets_sync":   {"emoji": "📊", "title": "Google Sheets sync",           "benefit": "export your portfolio live to Google Sheets",                "desc": "Live portfolio export with auto-formatting and signal colours.",                  "cta": "Upgrade to Starter"},
    "ai_chat":       {"emoji": "🤖", "title": "AI analyst chat",              "benefit": "ask unlimited AI questions about any stock",                 "desc": "50 AI questions/day on any stock analysis.",                                     "cta": "Upgrade to Starter"},
    "india":         {"emoji": "🇮🇳", "title": "Indian market access",        "benefit": "analyse NSE & BSE stocks with INR-calibrated WACC",          "desc": "500+ NSE & BSE stocks with INR-calibrated WACC and sector benchmarks.",          "cta": "Upgrade to Pro"},
    "europe":        {"emoji": "🌍", "title": "European market access",       "benefit": "analyse European stocks with local WACC",                    "desc": "Germany, UK, France, Netherlands with local WACC.",                              "cta": "Upgrade to Pro"},
    "portfolio":     {"emoji": "💼", "title": "Portfolio analyser",           "benefit": "track P&L and DCF score across your holdings",               "desc": "Aggregate DCF score across your holdings.",                                      "cta": "Upgrade to Starter"},
    "compare_stocks":{"emoji": "📊", "title": "Stock comparison",             "benefit": "compare any two stocks side-by-side",                        "desc": "Side-by-side DCF and fundamental comparison.",                                   "cta": "Upgrade to Starter"},
    "api_access":    {"emoji": "🔧", "title": "API access",                   "benefit": "power your own tools with 500 API calls/day",                "desc": "500 API calls/day to power your own tools.",                                     "cta": "Upgrade to Pro"},
    "bulk_screener": {"emoji": "⚡", "title": "Bulk screener",                "benefit": "screen all 1,500 S&P stocks on demand",                      "desc": "Screen all 1,500 S&P stocks on demand.",                                        "cta": "Upgrade to Pro"},
}


# ══════════════════════════════════════════════════════════════
# HELPER: skeleton preview HTML for blurred lock cards
# ══════════════════════════════════════════════════════════════

def _skeleton_preview(feature: str) -> str:
    """Placeholder HTML shown blurred behind the feature lock overlay."""
    _row  = '<div style="height:13px;background:#D1D5DB;border-radius:4px;margin:7px 0;"></div>'
    _row2 = '<div style="height:22px;background:#D1D5DB;border-radius:6px;margin:7px 0;"></div>'

    if feature in ("scenarios",):
        card = lambda bg: (
            f'<div style="padding:14px;background:{bg};border-radius:10px;">'
            f'{_row2}{_row}{_row}</div>'
        )
        return (
            '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">'
            + card("#FEE2E2") + card("#DBEAFE") + card("#D1FAE5") + "</div>"
        )

    if feature in ("sensitivity",):
        cells = "".join(
            f'<div style="height:30px;background:{"#BFDBFE" if (i+j)%3==0 else "#D1D5DB"};'
            f'border-radius:4px;"></div>'
            for j in range(4) for i in range(4)
        )
        return f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;">{cells}</div>'

    if feature in ("monte_carlo",):
        heights = [30, 50, 70, 90, 110, 130, 120, 100, 75, 55, 38, 22]
        bars = "".join(
            f'<div style="height:{h}px;width:7%;background:#93C5FD;border-radius:3px 3px 0 0;'
            f'display:inline-block;margin:0 1%;vertical-align:bottom;"></div>'
            for h in heights
        )
        return (
            f'<div style="text-align:center;padding:8px 12px;">{bars}</div>'
            f'<div style="height:3px;background:#D1D5DB;border-radius:2px;margin:4px 12px;"></div>'
        )

    if feature in ("quality_score",):
        boxes = "".join(
            f'<div style="flex:1;height:44px;background:{c};border-radius:8px;"></div>'
            for c in ["#BFDBFE", "#D1FAE5", "#FEF3C7", "#F3E8FF"]
        )
        return (
            f'{_row}{_row2}'
            f'<div style="display:flex;gap:8px;margin-top:10px;">{boxes}</div>'
        )

    # Generic fallback
    return f'{_row2}{_row}{_row}<div style="height:5px;background:#D1D5DB;border-radius:3px;margin-top:12px;"></div>'


# ══════════════════════════════════════════════════════════════
# 1 — FEATURE LOCK / TEASER CARD   (replaces old blur_and_lock)
# ══════════════════════════════════════════════════════════════

def blur_and_lock(feature: str, preview_html: str = "") -> None:
    """
    Show a teaser card for a locked feature:
      - blurred skeleton preview in the background
      - semi-transparent dark overlay
      - lock icon, feature name, one-line benefit, gold upgrade button
    """
    c   = UPGRADE_COPY.get(feature, {
        "emoji": "🔒", "title": "Premium feature",
        "benefit": "access this analysis", "cta": "Upgrade",
    })
    ph  = preview_html or _skeleton_preview(feature)
    benefit = c.get("benefit", "access this analysis")
    cta     = c.get("cta", "Upgrade")
    title   = c.get("title", "Premium feature")

    st.html(f"""
    <div style="position:relative;border-radius:14px;overflow:hidden;
                margin:10px 0;box-shadow:0 2px 16px rgba(0,0,0,0.08);">

      <!-- Blurred preview -->
      <div style="filter:blur(6px);pointer-events:none;user-select:none;
                  opacity:0.35;padding:22px;
                  background:#F8FAFC;border:1px solid #E2E8F0;border-radius:14px;">
        {ph}
      </div>

      <!-- Dark overlay -->
      <div style="position:absolute;inset:0;
                  background:rgba(10,18,35,0.75);
                  backdrop-filter:blur(1.5px);
                  display:flex;flex-direction:column;
                  align-items:center;justify-content:center;
                  padding:28px;text-align:center;">

        <div style="font-size:34px;margin-bottom:10px;">🔒</div>

        <div style="font-size:16px;font-weight:700;color:#FFFFFF;
                    font-family:Inter,sans-serif;margin-bottom:8px;">
          {title}
        </div>

        <div style="font-size:13px;color:rgba(255,255,255,0.65);
                    max-width:300px;line-height:1.65;margin-bottom:20px;">
          Unlock to {benefit}
        </div>

        <a href="{UPGRADE_URL}" target="_blank"
           style="display:inline-block;
                  background:linear-gradient(135deg,#D97706 0%,#F59E0B 100%);
                  color:#FFFFFF;font-size:13px;font-weight:700;
                  padding:11px 28px;border-radius:10px;
                  text-decoration:none;letter-spacing:0.01em;
                  box-shadow:0 4px 16px rgba(217,119,6,0.45);
                  transition:opacity 0.15s;">
          {cta} →
        </a>

        <div style="font-size:11px;color:rgba(255,255,255,0.38);
                    margin-top:10px;">
          Plans from $29/month
        </div>
      </div>
    </div>
    """)


# ══════════════════════════════════════════════════════════════
# 2 — UPGRADE BANNER   (slim, dismissible, resets daily)
# ══════════════════════════════════════════════════════════════

def render_upgrade_banner() -> None:
    """
    Slim banner at the top of the page for free-tier users.
    Shows remaining daily analyses. Dismissible — resets each day.
    Call this right after init_tier() in app.py's main body.
    """
    if tier() != "free":
        return

    today       = str(date.today())
    dismiss_key = f"_banner_dismissed_{today}"
    if st.session_state.get(dismiss_key):
        return

    used      = st.session_state.get("analyses_today", 0)
    total     = LIMITS["free"]["analyses_per_day"]
    remaining = max(0, total - used)
    em        = st.session_state.get("auth_email", "")

    word = "analysis" if remaining == 1 else "analyses"
    icon = "🔴" if remaining == 0 else ("🟡" if remaining <= 2 else "⚡")

    banner_col, btn_col, x_col = st.columns([7, 2, 1])

    with banner_col:
        st.html(f"""
        <div style="background:linear-gradient(90deg,#1E3A8A 0%,#1D4ED8 100%);
                    padding:11px 18px;border-radius:10px;
                    display:flex;align-items:center;gap:10px;">
          <span style="font-size:15px;flex-shrink:0;">{icon}</span>
          <span style="font-size:13px;color:#FFFFFF;font-weight:400;line-height:1.4;">
            You're on the <strong style="font-weight:700;">Free plan</strong>
            &nbsp;—&nbsp;
            <strong style="font-weight:700;">{remaining} {word}</strong>
            remaining today
          </span>
          <a href="{UPGRADE_URL}" target="_blank"
             style="margin-left:auto;font-size:12px;font-weight:700;
                    color:#BAE6FD;text-decoration:none;white-space:nowrap;
                    border:1px solid rgba(186,230,253,0.35);
                    padding:4px 12px;border-radius:6px;">
            Upgrade to Pro →
          </a>
        </div>
        """)

    with btn_col:
        pass  # upgrade link is inside the HTML above

    with x_col:
        if st.button("✕", key="_banner_dismiss_x", help="Dismiss for today"):
            _track_nudge(em, "free", "banner", "dismissed")
            st.session_state[dismiss_key] = True
            st.rerun()


# ══════════════════════════════════════════════════════════════
# RAZORPAY CHECKOUT
# ══════════════════════════════════════════════════════════════

def _launch_razorpay_checkout(email: str, chosen_tier: str, billing: str = "monthly") -> None:
    """Create a Razorpay subscription and open the checkout overlay."""
    rzp_key = os.environ.get("RAZORPAY_KEY_ID", "")
    if not rzp_key:
        st.error("Payment system not configured. Please contact support.")
        return

    try:
        from payments.razorpay_client import create_subscription
        sub = create_subscription(email, chosen_tier, billing)
        sub_id = sub["id"]
    except Exception as e:
        st.error(f"Could not create subscription: {e}")
        return

    app_url = os.environ.get("YIELDIQ_APP_URL", "")
    callback = f"{app_url}?payment_status=success&sub_id={sub_id}"

    import streamlit.components.v1 as components
    components.html(f"""
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script>
    var options = {{
        "key": "{rzp_key}",
        "subscription_id": "{sub_id}",
        "name": "YieldIQ",
        "description": "{chosen_tier.title()} Plan",
        "image": "",
        "handler": function(response) {{
            window.top.location.href = "{callback}" +
                "&razorpay_payment_id=" + response.razorpay_payment_id +
                "&razorpay_subscription_id=" + response.razorpay_subscription_id +
                "&razorpay_signature=" + response.razorpay_signature;
        }},
        "prefill": {{ "email": "{email}" }},
        "theme": {{ "color": "#1D4ED8" }},
        "modal": {{
            "ondismiss": function() {{
                // User closed checkout — do nothing
            }}
        }}
    }};
    var rzp = new Razorpay(options);
    rzp.open();
    </script>
    <div style="text-align:center;padding:40px;font-size:14px;color:#6B7280;">
      Loading payment gateway...
    </div>
    """, height=500)


def _handle_payment_callback() -> None:
    """Check query params for Razorpay payment callback and upgrade tier."""
    try:
        status = st.query_params.get("payment_status", "")
        if status != "success":
            return

        sub_id = st.query_params.get("razorpay_subscription_id", "") or st.query_params.get("sub_id", "")
        payment_id = st.query_params.get("razorpay_payment_id", "")
        signature = st.query_params.get("razorpay_signature", "")

        if not sub_id:
            return

        # Verify signature if available
        if payment_id and signature:
            from payments.razorpay_client import verify_payment_signature
            valid = verify_payment_signature({
                "razorpay_payment_id": payment_id,
                "razorpay_subscription_id": sub_id,
                "razorpay_signature": signature,
            })
            if not valid:
                st.error("Payment verification failed. Please contact support.")
                return

        # Look up subscription to get tier
        from payments.models import update_subscription_status, get_active_subscription
        email = st.session_state.get("auth_email", "")
        update_subscription_status(sub_id, "active", payment_id)

        # Determine tier from subscription
        sub = get_active_subscription(email)
        new_tier = sub["tier"] if sub else "starter"

        # Upgrade user
        st.session_state["tier"] = new_tier
        # Also update in auth.db
        try:
            import sqlite3
            from pathlib import Path
            db_path = Path(__file__).parent / "auth.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("UPDATE users SET tier = ? WHERE email = ?", (new_tier, email))
            conn.commit()
            conn.close()
        except Exception:
            pass

        # Clear payment params and show success
        try:
            for k in ["payment_status", "sub_id", "razorpay_payment_id",
                       "razorpay_subscription_id", "razorpay_signature"]:
                if k in st.query_params:
                    del st.query_params[k]
        except Exception:
            pass

        st.success(f"🎉 Welcome to YieldIQ {new_tier.title()}! Your account has been upgraded.")
        _init_usage_counters()
        st.rerun()

    except Exception as e:
        # Silently handle — don't break the app
        pass


# ══════════════════════════════════════════════════════════════
# 3 — PRICING PAGE   (full 3-column comparison with toggle)
# ══════════════════════════════════════════════════════════════

def render_pricing_page() -> None:
    """
    Full-width pricing comparison: FREE / STARTER / PRO.
    Includes Monthly/Annual toggle (Annual = 20% off).
    Call from app.py when user clicks an upgrade button.
    """
    em = st.session_state.get("auth_email", "")

    # ── Header ─────────────────────────────────────────────────
    st.html("""
    <div style="text-align:center;padding:24px 0 8px;">
      <div style="font-size:28px;font-weight:800;color:#111827;
                  font-family:Inter,sans-serif;letter-spacing:-0.02em;
                  margin-bottom:10px;">
        Simple, transparent pricing
      </div>
      <div style="font-size:15px;color:#6B7280;max-width:480px;
                  margin:0 auto;line-height:1.6;">
        Start free. Upgrade when you need more power.
        Cancel anytime.
      </div>
    </div>
    """)

    # ── Billing toggle ──────────────────────────────────────────
    _billing_key = "_pricing_billing"
    st.session_state.setdefault(_billing_key, "monthly")
    _, tog_col, _ = st.columns([2, 2, 2])
    with tog_col:
        billing = st.radio(
            "Billing cycle",
            options=["monthly", "annual"],
            format_func=lambda x: "Monthly" if x == "monthly" else "Annual  — save 20% 🎁",
            horizontal=True,
            label_visibility="collapsed",
            key=_billing_key,
        )
    annual = billing == "annual"

    s_price  = _STARTER_ANNUAL if annual else _STARTER_MONTHLY
    p_price  = _PRO_ANNUAL     if annual else _PRO_MONTHLY
    s_period = "/mo, billed annually" if annual else "/month"
    p_period = "/mo, billed annually" if annual else "/month"

    st.html('<div style="height:12px;"></div>')

    # ── Three tier columns ──────────────────────────────────────
    free_col, starter_col, pro_col = st.columns(3, gap="medium")

    # ·· FREE ···················································
    with free_col:
        st.html("""
        <div style="background:#FFFFFF;border:1.5px solid #E5E7EB;
                    border-radius:18px;padding:28px 24px;height:100%;">
          <div style="font-size:13px;font-weight:700;color:#6B7280;
                      letter-spacing:0.06em;text-transform:uppercase;
                      margin-bottom:12px;">Free</div>
          <div style="display:flex;align-items:baseline;gap:4px;margin-bottom:6px;">
            <span style="font-size:36px;font-weight:800;color:#111827;
                         font-family:Inter,sans-serif;">$0</span>
          </div>
          <div style="font-size:12px;color:#9CA3AF;margin-bottom:20px;">
            No credit card required
          </div>
          <hr style="border:none;border-top:1px solid #F3F4F6;margin:0 0 20px;">
          <div style="display:flex;flex-direction:column;gap:10px;">
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>5 analyses per day</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>10 watchlist stocks</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>Basic DCF valuation</span>
            </div>
            <div style="font-size:13px;color:#9CA3AF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#D1D5DB;flex-shrink:0;">✕</span>
              <span>PDF export</span>
            </div>
            <div style="font-size:13px;color:#9CA3AF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#D1D5DB;flex-shrink:0;">✕</span>
              <span>Price alerts</span>
            </div>
            <div style="font-size:13px;color:#9CA3AF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#D1D5DB;flex-shrink:0;">✕</span>
              <span>Scenario analysis</span>
            </div>
            <div style="font-size:13px;color:#9CA3AF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#D1D5DB;flex-shrink:0;">✕</span>
              <span>Monte Carlo simulation</span>
            </div>
          </div>
        </div>
        """)
        st.html('<div style="height:12px;"></div>')
        if st.button("Current plan", key="_pricing_free_btn",
                     use_container_width=True, disabled=is_free()):
            pass

    # ·· STARTER — Most Popular ·································
    with starter_col:
        st.html(f"""
        <div style="background:linear-gradient(160deg,#1E3A8A,#1D4ED8);
                    border:2px solid #1D4ED8;border-radius:18px;
                    padding:28px 24px;height:100%;position:relative;">

          <!-- Most Popular badge -->
          <div style="position:absolute;top:-14px;left:50%;transform:translateX(-50%);
                      background:linear-gradient(90deg,#D97706,#F59E0B);
                      color:#FFFFFF;font-size:10px;font-weight:800;
                      padding:4px 16px;border-radius:100px;
                      letter-spacing:0.10em;white-space:nowrap;">
            MOST POPULAR
          </div>

          <div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.70);
                      letter-spacing:0.06em;text-transform:uppercase;
                      margin-bottom:12px;">Starter</div>
          <div style="display:flex;align-items:baseline;gap:4px;margin-bottom:6px;">
            <span style="font-size:36px;font-weight:800;color:#FFFFFF;
                         font-family:Inter,sans-serif;">{s_price}</span>
          </div>
          <div style="font-size:12px;color:rgba(255,255,255,0.50);margin-bottom:20px;">
            {s_period}
          </div>
          <hr style="border:none;border-top:1px solid rgba(255,255,255,0.15);margin:0 0 20px;">
          <div style="display:flex;flex-direction:column;gap:10px;">
            <div style="font-size:13px;color:#FFFFFF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#6EE7B7;font-weight:700;flex-shrink:0;">✓</span>
              <span>50 analyses per day</span>
            </div>
            <div style="font-size:13px;color:#FFFFFF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#6EE7B7;font-weight:700;flex-shrink:0;">✓</span>
              <span>50 watchlist stocks</span>
            </div>
            <div style="font-size:13px;color:#FFFFFF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#6EE7B7;font-weight:700;flex-shrink:0;">✓</span>
              <span>All valuation models</span>
            </div>
            <div style="font-size:13px;color:#FFFFFF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#6EE7B7;font-weight:700;flex-shrink:0;">✓</span>
              <span>PDF reports (5/month)</span>
            </div>
            <div style="font-size:13px;color:#FFFFFF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#6EE7B7;font-weight:700;flex-shrink:0;">✓</span>
              <span>50 price alerts</span>
            </div>
            <div style="font-size:13px;color:#FFFFFF;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#6EE7B7;font-weight:700;flex-shrink:0;">✓</span>
              <span>Email support</span>
            </div>
            <div style="font-size:13px;color:rgba(255,255,255,0.45);
                        display:flex;gap:8px;align-items:flex-start;">
              <span style="color:rgba(255,255,255,0.25);flex-shrink:0;">✕</span>
              <span>API access</span>
            </div>
          </div>
        </div>
        """)
        st.html('<div style="height:12px;"></div>')
        if st.button("Choose Starter →", key="_pricing_starter_btn",
                     type="primary", use_container_width=True):
            _track_nudge(em, tier(), "pricing_page", "chose_starter")
            _launch_razorpay_checkout(em, "starter", billing)

    # ·· PRO ···················································
    with pro_col:
        st.html(f"""
        <div style="background:#F8FAFC;border:1.5px solid #E5E7EB;
                    border-radius:18px;padding:28px 24px;height:100%;">
          <div style="font-size:13px;font-weight:700;color:#059669;
                      letter-spacing:0.06em;text-transform:uppercase;
                      margin-bottom:12px;">Pro</div>
          <div style="display:flex;align-items:baseline;gap:4px;margin-bottom:6px;">
            <span style="font-size:36px;font-weight:800;color:#111827;
                         font-family:Inter,sans-serif;">{p_price}</span>
          </div>
          <div style="font-size:12px;color:#9CA3AF;margin-bottom:20px;">
            {p_period}
          </div>
          <hr style="border:none;border-top:1px solid #F3F4F6;margin:0 0 20px;">
          <div style="display:flex;flex-direction:column;gap:10px;">
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>Unlimited analyses</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>Unlimited watchlist</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>API access (500 calls/day)</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>Unlimited PDF reports</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>Bulk screener</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>Priority support</span>
            </div>
            <div style="font-size:13px;color:#374151;display:flex;gap:8px;align-items:flex-start;">
              <span style="color:#059669;font-weight:700;flex-shrink:0;">✓</span>
              <span>White-label PDF</span>
            </div>
          </div>
        </div>
        """)
        st.html('<div style="height:12px;"></div>')
        if st.button("Choose Pro →", key="_pricing_pro_btn",
                     use_container_width=True):
            _track_nudge(em, tier(), "pricing_page", "chose_pro")
            _launch_razorpay_checkout(em, "pro", billing)

    # ── Footer note ─────────────────────────────────────────────
    st.html("""
    <div style="text-align:center;margin-top:24px;font-size:12px;color:#9CA3AF;
                line-height:1.8;">
      All plans include a <strong style="color:#374151;">7-day free trial</strong>.
      No credit card required to start. Cancel anytime.
    </div>
    """)


# ══════════════════════════════════════════════════════════════
# 4 — USAGE METER   (sidebar progress bar for free users)
# ══════════════════════════════════════════════════════════════

def render_usage_meter() -> None:
    """
    Sidebar usage meter for free-tier users.
    Shows analyses used today, a progress bar, and time until reset.
    Call from app.py sidebar section.
    """
    if tier() not in ("free",):
        return

    used  = st.session_state.get("analyses_today", 0)
    total = LIMITS["free"]["analyses_per_day"]
    pct   = min(used / total * 100, 100) if total else 100

    if pct >= 100:
        bar_color, text_color = "#DC2626", "#DC2626"
    elif pct >= 60:
        bar_color, text_color = "#D97706", "#D97706"
    else:
        bar_color, text_color = "#1D4ED8", "#1D4ED8"

    # Time until midnight UTC
    _now = datetime.utcnow()
    _midnight = (_now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    _secs_left = int((_midnight - _now).total_seconds())
    _h, _rem   = divmod(_secs_left, 3600)
    _m         = _rem // 60
    reset_str  = f"{_h}h {_m}m" if _h else f"{_m}m"

    st.sidebar.html(f"""
    <div style="padding:14px 16px;background:#F8FAFC;
                border:1px solid #E5E7EB;border-radius:12px;margin:6px 0 4px;">
      <div style="display:flex;justify-content:space-between;
                  align-items:center;margin-bottom:8px;">
        <div style="font-size:11px;font-weight:700;color:#374151;
                    letter-spacing:0.05em;text-transform:uppercase;">
          Daily Analyses
        </div>
        <div style="font-size:12px;font-weight:700;color:{text_color};">
          {used}/{total} used
        </div>
      </div>

      <!-- Progress bar -->
      <div style="height:6px;background:#E5E7EB;border-radius:3px;overflow:hidden;">
        <div style="height:100%;width:{pct:.1f}%;background:{bar_color};
                    border-radius:3px;"></div>
      </div>

      <!-- Reset label -->
      <div style="font-size:10px;color:#9CA3AF;margin-top:7px;
                  display:flex;justify-content:space-between;">
        <span>Resets in {reset_str}</span>
        <a href="{UPGRADE_URL}" target="_blank"
           style="color:#1D4ED8;text-decoration:none;font-weight:600;">
          Upgrade ↗
        </a>
      </div>
    </div>
    """)


# ══════════════════════════════════════════════════════════════
# EXISTING UI HELPERS  (preserved + visual polish)
# ══════════════════════════════════════════════════════════════

def upgrade_prompt(feature: str, compact: bool = False) -> None:
    """Inline upgrade prompt — compact (row) or full-width card."""
    c = UPGRADE_COPY.get(feature, {
        "emoji": "🔒", "title": "Starter feature",
        "benefit": "access this feature", "cta": "Upgrade to Starter",
        "desc": "Upgrade to unlock.",
    })

    if compact:
        st.html(
            f'<div style="display:flex;align-items:center;gap:12px;padding:12px 16px;'
            f'background:#FFFBEB;border:1.5px solid #FDE68A;border-radius:10px;margin:8px 0;">'
            f'<span style="font-size:20px;">{c["emoji"]}</span>'
            f'<div style="flex:1;">'
            f'<div style="font-size:13px;font-weight:600;color:#111827;">{c["title"]}</div>'
            f'<div style="font-size:12px;color:#6B7280;">{c.get("desc","")}</div>'
            f'</div>'
            f'<a href="{UPGRADE_URL}" target="_blank" '
            f'style="background:linear-gradient(135deg,#D97706,#F59E0B);color:#fff;'
            f'font-size:12px;font-weight:700;padding:7px 16px;border-radius:8px;'
            f'text-decoration:none;white-space:nowrap;">'
            f'{c["cta"]} →</a></div>'
        )
    else:
        st.html(
            f'<div style="padding:32px 28px;background:#FFFFFF;'
            f'border:1.5px solid #FDE68A;border-radius:16px;text-align:center;margin:12px 0;">'
            f'<div style="font-size:38px;margin-bottom:12px;">{c["emoji"]}</div>'
            f'<div style="font-size:18px;font-weight:700;color:#111827;margin-bottom:8px;">{c["title"]}</div>'
            f'<div style="font-size:13px;color:#6B7280;margin-bottom:24px;'
            f'max-width:360px;margin-left:auto;margin-right:auto;line-height:1.65;">'
            f'{c.get("desc","")}</div>'
            f'<a href="{UPGRADE_URL}" target="_blank" '
            f'style="display:inline-block;'
            f'background:linear-gradient(135deg,#D97706 0%,#F59E0B 100%);'
            f'color:#fff;font-size:14px;font-weight:700;'
            f'padding:12px 32px;border-radius:10px;text-decoration:none;'
            f'box-shadow:0 4px 16px rgba(217,119,6,0.35);">'
            f'{c["cta"]} →</a>'
            f'<div style="font-size:11px;color:#9CA3AF;margin-top:12px;">'
            f'Plans from $29/month</div>'
            f'</div>'
        )


def tier_badge_html() -> str:
    t     = tier()
    color = TIER_COLORS.get(t, "#6B7280")
    em    = st.session_state.get("auth_email", "")
    eml   = (
        f'<div style="font-size:10px;color:{color};opacity:.7;margin-top:2px;">{em}</div>'
    ) if em and em != "guest" else ""
    name  = TIER_NAMES.get(t, t.capitalize())
    price = {"free": "$0", "starter": _STARTER_MONTHLY, "pro": _PRO_MONTHLY}.get(t, "")
    return (
        f'<div style="text-align:center;">'
        f'<span style="background:{color}18;border:1.5px solid {color}44;color:{color};'
        f'font-size:11px;font-weight:700;padding:3px 12px;border-radius:100px;">'
        f'{name} — {price}</span>{eml}</div>'
    )


def usage_bar_html() -> str:
    """Compact HTML for sidebar — analyses + reports bars + sign-out link."""
    t  = tier()
    ua = st.session_state.get("analyses_today", 0)
    la = LIMITS[t]["analyses_per_day"]
    ur = st.session_state.get("reports_month", 0)
    lr = LIMITS[t]["reports_per_month"]

    if la >= 9999:
        ab = '<span style="color:#059669;font-size:11px;">Unlimited analyses</span>'
    else:
        pct = min(ua / la * 100, 100) if la else 100
        clr = "#DC2626" if pct >= 100 else "#D97706" if pct >= 66 else "#1D4ED8"
        ab = (
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:11px;color:#6B7280;margin-bottom:3px;">'
            f'<span>Analyses today</span><span style="font-weight:700;color:{clr};">{ua}/{la}</span></div>'
            f'<div style="height:5px;background:#E5E7EB;border-radius:3px;margin-bottom:8px;">'
            f'<div style="height:100%;width:{pct:.0f}%;background:{clr};border-radius:3px;"></div></div>'
        )

    if lr == 0:
        rb = '<span style="color:#9CA3AF;font-size:11px;">No reports included</span>'
    elif lr >= 9999:
        rb = '<span style="color:#059669;font-size:11px;">Unlimited reports</span>'
    else:
        pct = min(ur / lr * 100, 100) if lr else 100
        clr = "#DC2626" if pct >= 100 else "#D97706" if pct >= 66 else "#1D4ED8"
        rb = (
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:11px;color:#6B7280;margin-bottom:3px;margin-top:6px;">'
            f'<span>Reports this month</span><span style="font-weight:700;color:{clr};">{ur}/{lr}</span></div>'
            f'<div style="height:5px;background:#E5E7EB;border-radius:3px;">'
            f'<div style="height:100%;width:{pct:.0f}%;background:{clr};border-radius:3px;"></div></div>'
        )

    return (
        ab + rb
        + f'<div style="text-align:center;margin-top:10px;">'
          f'<a href="?signout=1" style="font-size:11px;color:#1D4ED8;">Sign out</a>'
          f'</div>'
    )


# ══════════════════════════════════════════════════════════════
# SMART UPGRADE PROMPTS  (existing — preserved with minor polish)
# ══════════════════════════════════════════════════════════════

def show_analysis_limit_modal() -> None:
    """Rich upgrade card shown when a free user exhausts their daily analyses."""
    em = st.session_state.get("auth_email", "")
    if not st.session_state.get("_nudge_limit_shown"):
        st.session_state["_nudge_limit_shown"] = True
        _track_nudge(em, tier(), "analysis_limit", "shown")

    with st.container(border=True):
        st.html("""
        <div style="text-align:center;padding:16px 0 20px;">
          <div style="font-size:48px;margin-bottom:12px;">🔒</div>
          <div style="font-size:21px;font-weight:800;color:#111827;
                      font-family:Inter,sans-serif;margin-bottom:8px;">
            You've used all 5 free analyses today
          </div>
          <div style="font-size:14px;color:#6B7280;line-height:1.6;">
            Upgrade for more analyses — or come back tomorrow.
          </div>
        </div>
        """)

        # Annual / Monthly toggle
        _billing_key = "_limit_modal_billing"
        st.session_state.setdefault(_billing_key, "monthly")
        _bc1, _bc2, _bc3 = st.columns([1, 2, 1])
        with _bc2:
            _billing = st.radio(
                "Billing",
                options=["monthly", "annual"],
                format_func=lambda x: "Monthly" if x == "monthly" else "Annual  (2 months free 🎁)",
                horizontal=True,
                label_visibility="collapsed",
                key=_billing_key,
            )
        _annual  = (_billing == "annual")
        _s_price = _STARTER_ANNUAL if _annual else _STARTER_MONTHLY
        _p_price = _PRO_ANNUAL     if _annual else _PRO_MONTHLY

        # Comparison table
        st.markdown(f"""
| Feature | Free | Starter | Pro |
|---|:---:|:---:|:---:|
| Analyses / day | **5** | 50 | Unlimited |
| Watchlist stocks | 10 | 50 | Unlimited |
| US stocks (DCF) | ✅ | ✅ | ✅ |
| Indian stocks (NSE/BSE) | ❌ | ❌ | ✅ |
| European markets | ❌ | ❌ | ✅ |
| Scenario analysis | ❌ | ✅ | ✅ |
| Monte Carlo simulation | ❌ | ❌ | ✅ |
| Stock screener | ❌ | ✅ | ✅ |
| Excel + PDF export | ❌ | ✅ | ✅ |
| API access | ❌ | ❌ | ✅ (500/day) |
| **Price** | **$0** | **{_s_price}** | **{_p_price}** |
""")

        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            if st.button("🚀 Start 7-day free trial", key="_nudge_trial_cta",
                         use_container_width=True, type="primary"):
                _track_nudge(em, tier(), "analysis_limit", "clicked_trial")
                st.markdown(f'<meta http-equiv="refresh" content="0;url={UPGRADE_URL}">',
                            unsafe_allow_html=True)
        with c2:
            if st.button("View all plans →", key="_nudge_plans_cta",
                         use_container_width=True):
                _track_nudge(em, tier(), "analysis_limit", "clicked_plans")
                st.markdown(f'<meta http-equiv="refresh" content="0;url={PRICING_URL}">',
                            unsafe_allow_html=True)
        with c3:
            st.html('<div style="font-size:11px;color:#9CA3AF;padding-top:8px;'
                    'text-align:center;">Resets midnight UTC</div>')


def show_india_gate_message() -> None:
    """Inline contextual nudge when a free user tries an Indian stock."""
    em = st.session_state.get("auth_email", "")
    if not st.session_state.get("_nudge_india_shown"):
        st.session_state["_nudge_india_shown"] = True
        _track_nudge(em, tier(), "india_gate", "shown")

    st.html(
        '<div style="display:flex;align-items:flex-start;gap:14px;padding:16px 20px;'
        'background:#FFF7ED;border:1.5px solid #FED7AA;border-radius:12px;margin:12px 0;">'
        '<div style="font-size:28px;line-height:1;">🇮🇳</div>'
        '<div style="flex:1;">'
        '<div style="font-size:14px;font-weight:700;color:#9A3412;margin-bottom:4px;">'
        'Indian market access requires Pro</div>'
        '<div style="font-size:13px;color:#7C2D12;line-height:1.6;">'
        '500+ NSE &amp; BSE stocks — INR-calibrated WACC and sector benchmarks.<br>'
        'Upgrade to analyse Reliance, Infosys, HDFC Bank and more.</div>'
        f'<div style="margin-top:12px;">'
        f'<a href="{UPGRADE_URL}" style="background:#EA580C;color:#fff;font-size:13px;'
        f'font-weight:600;padding:8px 18px;border-radius:8px;text-decoration:none;">'
        f'Unlock Indian Stocks — Pro {_PRO_MONTHLY} →</a></div>'
        '</div></div>'
    )
    if st.button("Upgrade to Pro for Indian stocks →", key="_nudge_india_cta"):
        _track_nudge(em, tier(), "india_gate", "clicked")
        st.markdown(f'<meta http-equiv="refresh" content="0;url={UPGRADE_URL}">',
                    unsafe_allow_html=True)


def show_report_upsell() -> None:
    """Pro upsell nudge shown to Starter users who exhaust their monthly reports."""
    em   = st.session_state.get("auth_email", "")
    used = st.session_state.get("reports_month", 0)
    lim  = LIMITS[tier()].get("reports_per_month", 0)

    if tier() != "starter" or used < lim:
        return

    if not st.session_state.get("_nudge_report_upsell_shown"):
        st.session_state["_nudge_report_upsell_shown"] = True
        _track_nudge(em, tier(), "report_upsell", "shown")

    st.html(
        '<div style="display:flex;align-items:flex-start;gap:14px;padding:16px 20px;'
        'background:#F0FDF4;border:1.5px solid #86EFAC;border-radius:12px;margin:12px 0;">'
        '<div style="font-size:28px;line-height:1;">📊</div>'
        '<div style="flex:1;">'
        '<div style="font-size:14px;font-weight:700;color:#14532D;margin-bottom:4px;">'
        "You're a power user — consider upgrading to Pro</div>"
        '<div style="font-size:13px;color:#166534;line-height:1.6;">'
        "You've hit your 5-report monthly limit. Pro users get <strong>unlimited reports</strong>, "
        "Monte Carlo simulation, Indian &amp; European markets, and 500 API calls/day.</div>"
        f'<div style="margin-top:12px;">'
        f'<a href="{UPGRADE_URL}" style="background:#059669;color:#fff;font-size:13px;'
        f'font-weight:600;padding:8px 18px;border-radius:8px;text-decoration:none;">'
        f'Upgrade to Pro — {_PRO_MONTHLY} →</a></div>'
        '</div></div>'
    )
    if st.button("Upgrade to Pro →", key="_nudge_report_upsell_cta"):
        _track_nudge(em, tier(), "report_upsell", "clicked")
        st.markdown(f'<meta http-equiv="refresh" content="0;url={UPGRADE_URL}">',
                    unsafe_allow_html=True)


def sidebar_upgrade_button() -> None:
    """Persistent upgrade button in sidebar — free users only."""
    if tier() != "free":
        return
    em = st.session_state.get("auth_email", "")
    st.sidebar.markdown("---")
    st.sidebar.html(
        f'<div style="text-align:center;margin-bottom:6px;">'
        f'<span style="font-size:11px;color:#6B7280;">'
        f'✨ Unlock more — Starter from {_STARTER_MONTHLY}</span></div>'
    )
    if st.sidebar.button("⚡ Upgrade to Starter", key="_sidebar_upgrade_btn",
                         use_container_width=True, type="primary"):
        _track_nudge(em, tier(), "sidebar_upgrade", "clicked")
        st.session_state["main_tab"] = "pricing"
        st.rerun()
    if st.sidebar.button("Compare plans", key="_sidebar_compare_plans",
                         use_container_width=True):
        st.session_state["main_tab"] = "pricing"
        st.rerun()
