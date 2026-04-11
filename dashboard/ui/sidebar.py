"""dashboard/ui/sidebar.py
Bloomberg Terminal-style sidebar — moved from app.py.
"""
from __future__ import annotations
import streamlit as st


def render_sidebar(
    *,
    CURRENCIES: dict,
    FORECAST_YEARS: int,
    fetch_market_pulse,
    get_fx_rate,
    ob_tooltip,
    can,
    tier,
    usage_bar_html,
    sidebar_upgrade_button,
    render_resume_button,
) -> dict:
    """Render the full sidebar and return a dict of user-chosen values.

    Returns dict with keys:
        sym, to_code, cur_key, fx_rate, fx_inr,
        use_auto_wacc, manual_wacc, terminal_g, forecast_yrs,
        run_mc, pro_mode, results_file
    """
    _active_main_tab = st.session_state.get("main_tab", "stock")

    with st.sidebar:
        # ── Chip CSS (kept inline for sidebar scope) ─────────────
        st.html("""
<style>
.yiq-chip {
  display:inline-block; font-family:'IBM Plex Mono',monospace;
  font-size:11px; font-weight:600; padding:3px 10px;
  background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.14);
  border-radius:5px; color:#94A3B8; margin:2px; cursor:pointer;
  transition:background 0.15s, color 0.15s;
}
.yiq-chip:hover { background:rgba(0,180,216,0.15); color:#00b4d8;
                  border-color:rgba(0,180,216,0.35); }
</style>
""")

        # ── 1. LOGO ──────────────────────────────────────────────
        import base64 as _b64, pathlib as _logo_pl
        _logo_path = _logo_pl.Path(__file__).resolve().parent.parent / "static" / "logo_circle.jpeg"
        if not _logo_path.exists():
            _logo_path = _logo_pl.Path(__file__).resolve().parent.parent / "static" / "logo_dark.jpeg"
        if _logo_path.exists():
            _logo_b64 = _b64.b64encode(_logo_path.read_bytes()).decode()
            st.html(f"""
    <div style="padding:20px 0 12px;text-align:center;">
      <div style="display:inline-block;width:72px;height:72px;border-radius:50%;
                  overflow:hidden;box-shadow:0 0 24px rgba(29,78,216,0.5),
                  0 0 48px rgba(6,182,212,0.15);">
        <img src="data:image/jpeg;base64,{_logo_b64}"
             style="width:100%;height:100%;object-fit:cover;transform:scale(1.25);" alt="YieldIQ"/>
      </div>
      <div style="margin-top:10px;font-size:15px;font-weight:800;color:#F1F5F9;
                  letter-spacing:-0.02em;">YieldIQ</div>
      <div style="font-size:8px;color:#64748B;letter-spacing:0.12em;
                  font-weight:500;text-transform:uppercase;margin-top:2px;">
        Quantitative Research
      </div>
      <div style="height:1px;background:linear-gradient(90deg,transparent,
                  rgba(29,78,216,0.3),rgba(6,182,212,0.3),transparent);
                  margin-top:14px;"></div>
    </div>
    """)
        else:
            st.html("""
    <div style="padding:14px 4px 14px;">
      <div style="font-size:17px;font-weight:800;color:#FFFFFF;
                  letter-spacing:-0.02em;line-height:1.1;">YieldIQ</div>
      <div style="font-size:9px;color:#64748B;letter-spacing:0.08em;
                  font-weight:500;margin-top:2px;">Quantitative research platform</div>
      <div style="height:1px;
                  background:linear-gradient(90deg,#1D4ED8,#06B6D4,transparent);
                  margin-top:10px;opacity:0.5;"></div>
    </div>
    """)

        # ── 2. VERTICAL NAV MENU ─────────────────────────────────
        # Groups: None = regular item, "divider" = insert hr before next group
        _NAV_ITEMS = [
            ("\U0001f3e0", "Home",  "morning_brief"),
            ("\U0001f50d", "Stock Analysis", "stock"),
            None,                                           # ── divider ──
            ("\U0001f4ca", "Financials",     "financials"),
            ("\U0001f3ed", "Sector Map",     "markets"),
            ("\u2696\ufe0f", "Compare",        "compare"),
            None,                                           # ── divider ──
            ("\U0001f4bc", "Portfolio",      "portfolio"),
            ("\U0001f4cb", "Screener",       "screener"),
            ("\U0001f4c5", "Earnings",       "earnings"),
            None,                                           # ── divider ──
            ("\u2699\ufe0f", "Settings",       "about"),
        ]
        _is_brief = (
            _active_main_tab == "stock"
            and not st.session_state.get("fin_ticker")
        )
        for _nav_item in _NAV_ITEMS:
            if _nav_item is None:
                st.markdown("---")
                continue
            _nav_icon, _nav_label, _nav_key = _nav_item
            _nav_active = (
                (_nav_key == "morning_brief" and _is_brief)
                or (_nav_key != "morning_brief" and _active_main_tab == _nav_key)
                or (_nav_key == "stock" and _active_main_tab == "stock" and not _is_brief)
            )
            if st.button(
                f"{_nav_icon}  {_nav_label}",
                key=f"nav_{_nav_key}",
                use_container_width=True,
                type="primary" if _nav_active else "secondary",
            ):
                if _nav_key == "morning_brief":
                    st.session_state["main_tab"] = "stock"
                    st.session_state["_show_morning_brief"] = True
                else:
                    st.session_state["main_tab"] = _nav_key
                    st.session_state.pop("_show_morning_brief", None)
                st.rerun()

        # ── 2b. THEME INDICATOR ────────────────────────────────��─
        st.markdown("---")
        _theme_key = st.session_state.get("theme", "slate")
        # Quick-cycle through themes from sidebar
        _theme_cycle = ["forest", "ocean", "aurora", "sakura", "violet", "slate"]
        _theme_names = {
            "forest": "\U0001f33f Forest", "ocean": "\U0001f30a Ocean",
            "aurora": "\U0001f305 Aurora", "sakura": "\U0001f338 Sakura",
            "violet": "\U0001f49c Violet", "slate": "\U0001faa8 Slate",
        }
        _cur_label = _theme_names.get(_theme_key, _theme_key)
        if st.button(f"\U0001f3a8  {_cur_label}", key="sb_theme_toggle", use_container_width=True):
            _idx = _theme_cycle.index(_theme_key) if _theme_key in _theme_cycle else 0
            st.session_state["theme"] = _theme_cycle[(_idx + 1) % len(_theme_cycle)]
            st.rerun()

        # ── 3. MARKET PULSE ──────────────────────────────────────
        st.html('<div class="yiq-sb-divider"></div>'
                '<div class="yiq-sb-section-label">Market Pulse</div>')
        _pulse = fetch_market_pulse()
        _pulse_fmt = {
            "S&P 500":   lambda p: f"{p:,.0f}",
            "10Y Yield": lambda p: f"{p:.2f}%",
            "VIX":       lambda p: f"{p:.2f}",
        }
        _pulse_rows = ""
        for _pname, _pdata in _pulse.items():
            _pchg  = _pdata["chg"]
            _pclr  = "yiq-pulse-chg-pos" if _pchg >= 0 else "yiq-pulse-chg-neg"
            _psym  = "\u25b2" if _pchg >= 0 else "\u25bc"
            _pfmt  = _pulse_fmt.get(_pname, lambda p: f"{p:,.2f}")
            _pval  = _pfmt(_pdata["price"]) if _pdata["price"] else "\u2014"
            _pulse_rows += (
                f'<div class="yiq-pulse-row">'
                f'<span class="yiq-pulse-label">{_pname}</span>'
                f'<span class="yiq-pulse-val">{_pval} '
                f'<span class="{_pclr}">{_psym}{abs(_pchg):.2f}%</span></span>'
                f'</div>'
            )
        st.html(f'<div class="yiq-pulse">{_pulse_rows}</div>')

        # ── 4. CONTROLS (currency, WACC, FX) ─────────────────────
        st.html('<div class="yiq-sb-divider"></div>')
        st.html('<div style="font-size:11px;font-weight:700;color:#38BDF8;'
                'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">\U0001f4b1 Currency</div>')
        cur_key = st.selectbox("Currency", list(CURRENCIES.keys()), index=1,
                               label_visibility="collapsed", key="sb_currency")
        sym     = CURRENCIES[cur_key]["symbol"]
        to_code = CURRENCIES[cur_key]["code"]

        st.html('<div style="height:1px;background:rgba(255,255,255,0.08);margin:8px 0;"></div>')
        st.html('<div style="font-size:11px;font-weight:700;color:#38BDF8;'
                'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">VIEW MODE</div>')
        _mode_col1, _mode_col2 = st.columns(2)
        with _mode_col1:
            if st.button("\U0001f4d6 Simple", width='stretch',
                         type="primary" if not st.session_state.get("pro_mode", False) else "secondary",
                         key="btn_simple_mode"):
                st.session_state["pro_mode"] = False
                st.rerun()
        with _mode_col2:
            if st.button("\u26a1 Pro", width='stretch',
                         type="primary" if st.session_state.get("pro_mode", False) else "secondary",
                         key="btn_pro_mode"):
                st.session_state["pro_mode"] = True
                st.rerun()
        pro_mode = st.session_state.get("pro_mode", False)

        with st.expander("\u2699\ufe0f Model Parameters", expanded=False):
            use_auto_wacc = st.toggle("Auto-calculate required return", value=True,
                                      key="sb_auto_wacc",
                                      help=ob_tooltip("wacc"))
            manual_wacc   = st.slider("Manual required return (%)", 8, 20, 10, 1,
                                      format="%d%%", disabled=use_auto_wacc,
                                      key="sb_manual_wacc",
                                      help=ob_tooltip("wacc"))
            terminal_pct  = st.slider("Long-run growth (%)", 1, 4, 3, 1,
                                      format="%d%%", key="sb_terminal_pct",
                                      help=ob_tooltip("terminal_g"))
            terminal_g    = terminal_pct / 100
            forecast_yrs  = st.slider("Years to forecast", 5, 15, FORECAST_YEARS,
                                      key="sb_forecast_yrs",
                                      help=ob_tooltip("forecast_yrs"))
            _mc_allowed = can("monte_carlo")
            run_mc = st.toggle(
                "Run 1,000 simulations",
                value=False, disabled=not _mc_allowed,
                help="Upgrade to Pro to unlock" if not _mc_allowed
                     else "Monte Carlo: 1,000 valuation scenarios",
                key="sb_run_mc",
            )
            if not _mc_allowed:
                st.html('<div style="font-size:11px;color:#8492a6;margin-top:-6px;">'
                        '\U0001f512 <a href="https://yieldiq.app/pricing.html" target="_blank" '
                        'style="color:#5046e4">Pro feature</a></div>')
            st.html('<div style="height:4px"></div>')
            if st.button("\U0001f5d1 Clear Cache & Refresh", width='stretch',
                         key="sb_clear_cache"):
                st.cache_data.clear()
                st.rerun()

        if st.session_state.get("_last_to_code") != to_code:
            st.session_state["_fx_rate_usd"] = get_fx_rate("USD", to_code)
            st.session_state["_fx_rate_inr"] = get_fx_rate("INR", to_code)
            st.session_state["_last_to_code"] = to_code
        fx_rate = st.session_state.get("_fx_rate_usd", 1.0)
        fx_inr  = st.session_state.get("_fx_rate_inr", 1.0)

        with st.expander("\U0001f4e1 Live Data & FX", expanded=False):
            st.html(f"""
        <div style="padding:8px 12px;background:rgba(255,255,255,0.04);
                    border-radius:8px;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:5px;margin-bottom:6px;">
            <div style="width:6px;height:6px;background:#34D399;border-radius:50%;
                        animation:shimmer 2s ease-in-out infinite;"></div>
            <span style="font-size:11px;color:#34D399;font-weight:700;
                         letter-spacing:0.04em;">LIVE FX</span>
          </div>
          <div style="font-size:11px;color:#94A3B8;
                      font-family:'IBM Plex Mono',monospace;line-height:2;">
            1 USD = <span style="color:#F1F5F9;font-weight:600;">
                    {sym}{fx_rate:,.2f}</span><br>
            1 INR = <span style="color:#F1F5F9;font-weight:600;">
                    {sym}{fx_inr:,.4f}</span>
          </div>
        </div>
        <div style="font-size:11px;color:#64748B;line-height:1.7;">
          Data: Yahoo Finance (yfinance)<br>
          Prices update every 60s
        </div>
        """)

        # ── Portfolio capital (silent) ───────────────────────────
        if "portfolio_capital" not in st.session_state:
            st.session_state["portfolio_capital"] = 10_000_000
        results_file = None

        # ── Recent Tickers ───────────────────────────────────────
        if "recent_tickers" not in st.session_state:
            st.session_state["recent_tickers"] = []
        _recent = st.session_state.get("recent_tickers", [])
        if _recent:
            st.html('<div style="font-size:11px;font-weight:700;color:#38BDF8;'
                    'letter-spacing:0.1em;text-transform:uppercase;'
                    'margin:10px 0 6px;">\U0001f4cc Recent</div>')
            _chips_html = '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;">'
            for _tk in _recent[-5:][::-1]:
                _chips_html += f'<span class="yiq-chip">{_tk}</span>'
            _chips_html += '</div>'
            st.html(_chips_html)
            _btn_cols = st.columns(min(len(_recent[-5:]), 3))
            for _i, _tk in enumerate(_recent[-5:][::-1][:3]):
                with _btn_cols[_i]:
                    if st.button(_tk, key=f"recent_{_tk}_{_i}", width='stretch'):
                        st.session_state["_prefill_ticker"] = _tk
                        st.session_state["main_tab"] = "stock"
                        st.rerun()

        # ── 5. USER PROFILE (bottom) ─────────────────────────────
        st.html('<div class="yiq-sb-divider" style="margin-top:12px;"></div>')
        _up_email    = st.session_state.get("auth_email", "guest")
        _up_tier     = tier()
        _up_tname    = {"free": "FREE", "starter": "STARTER",
                        "premium": "STARTER", "pro": "PRO"}.get(_up_tier, "FREE")
        _up_tclr_cls = {"free": "yiq-tier-free", "starter": "yiq-tier-starter",
                        "premium": "yiq-tier-starter", "pro": "yiq-tier-pro"
                        }.get(_up_tier, "yiq-tier-free")
        _up_email_disp = (
            (_up_email[:22] + "\u2026") if len(_up_email) > 24 else _up_email
        )
        _up_email_html = (
            f'<div class="yiq-profile-email">{_up_email_disp}</div>'
            if _up_email and _up_email != "guest"
            else '<div class="yiq-profile-email" style="color:#475569;">Not signed in</div>'
        )
        _usage_html = usage_bar_html()
        st.html(
            f'<div class="yiq-profile">'
            f'{_up_email_html}'
            f'<span class="yiq-tier-badge {_up_tclr_cls}">{_up_tname}</span>'
            f'<div style="margin-top:8px;">{_usage_html}</div>'
            f'</div>'
        )
        sidebar_upgrade_button()
        render_resume_button()

        # ── Disclaimer strip ─────────────────────────────────────
        st.html("""
    <div style="margin-top:10px;padding:8px 10px;
                background:rgba(251,191,36,0.06);
                border:1px solid rgba(251,191,36,0.15);border-radius:7px;">
      <div style="font-size:10px;color:#92400E;line-height:1.7;">
        \u26a0 Model output only \u2014 not investment advice<br>
        <span style="color:#475569;">YieldIQ is not a registered RIA</span>
      </div>
    </div>
    """)

        st.markdown("---")
        st.caption(
            "\u2696\ufe0f Model outputs only. Not investment advice. "
            "YieldIQ is not an SEC-registered investment adviser."
        )

    return {
        "sym": sym,
        "to_code": to_code,
        "cur_key": cur_key,
        "fx_rate": fx_rate,
        "fx_inr": fx_inr,
        "use_auto_wacc": use_auto_wacc,
        "manual_wacc": manual_wacc,
        "terminal_g": terminal_g,
        "forecast_yrs": forecast_yrs,
        "run_mc": run_mc,
        "pro_mode": pro_mode,
        "results_file": results_file,
    }
