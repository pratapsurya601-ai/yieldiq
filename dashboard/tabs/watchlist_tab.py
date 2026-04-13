"""dashboard/tabs/watchlist_tab.py
Watchlist tab — moved from app.py.
"""
from __future__ import annotations
import streamlit as st
from datetime import datetime
import importlib.util as _ilu, pathlib as _pl
_dh_path = _pl.Path(__file__).resolve().parent.parent / "utils" / "data_helpers.py"
_dh_spec = _ilu.spec_from_file_location("_yiq_dh", _dh_path)
_dh_mod  = _ilu.module_from_spec(_dh_spec); _dh_spec.loader.exec_module(_dh_mod)
CURRENCIES = _dh_mod.CURRENCIES
from portfolio import get_watchlist, remove_from_watchlist


def render() -> None:
    """Render the Watchlist tab."""
    _cur = st.session_state.get("sb_currency", "INR")
    sym  = CURRENCIES[_cur]["symbol"]


    # ── Live price helper (cached 2 min) ──────────────────────
    @st.cache_data(ttl=120, show_spinner=False)
    def _wl_fetch_price(ticker: str) -> tuple:
        """Returns (last_price, day_change_pct)."""
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).fast_info
            price = float(getattr(info, "last_price", 0) or 0)
            prev  = float(getattr(info, "previous_close", 0) or 0)
            chg   = ((price - prev) / prev * 100) if prev > 0 else 0.0
            return price, chg
        except Exception as _wl_pe:
            return 0.0, 0.0

    # ── Load watchlist items ──────────────────────────────────
    _wl_items = get_watchlist()
    _wl_now   = datetime.now().strftime("%H:%M:%S")

    # ── Enrich each item with live price + current MoS ───────
    _wl_enriched = []
    for _wl_item in _wl_items:
        _live_px, _day_chg = _wl_fetch_price(_wl_item["ticker"])
        _tgt = _wl_item["target_price"]
        _cur_mos = ((_tgt - _live_px) / _live_px * 100) if (_live_px > 0 and _tgt > 0) else 0.0
        _wl_enriched.append({
            **_wl_item,
            "live_price":  _live_px,
            "day_chg_pct": _day_chg,
            "current_mos": _cur_mos,
        })

    # ── 🔔 Alert banners — show BEFORE anything else ─────────
    for _wl_a in _wl_enriched:
        if _wl_a["live_price"] > 0 and _wl_a["current_mos"] >= _wl_a["alert_mos_threshold"]:
            st.warning(
                f"🔔 **Alert: {_wl_a['ticker']}** has crossed your "
                f"{_wl_a['alert_mos_threshold']:.0f}% MoS threshold — "
                f"currently at **{_wl_a['current_mos']:.1f}%** "
                f"(Target: {sym}{_wl_a['target_price']:,.2f} vs Live: {sym}{_wl_a['live_price']:,.2f})"
            )

    # ── Summary bar ───────────────────────────────────────────
    _wl_n_total = len(_wl_enriched)
    _wl_n_under = sum(1 for w in _wl_enriched if w["current_mos"] > 10)
    _wl_n_alert = sum(1 for w in _wl_enriched if w["current_mos"] >= w["alert_mos_threshold"])

    st.html(f"""
    <div style="display:flex;align-items:center;gap:0;
                background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;
                overflow:hidden;margin-bottom:14px;">
      <div style="padding:12px 20px;border-right:1px solid #F1F5F9;flex:1;">
        <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.12em;margin-bottom:3px;">Watching</div>
        <div style="font-size:20px;font-weight:700;color:#0F172A;
                    font-family:'IBM Plex Mono',monospace;">{_wl_n_total}</div>
      </div>
      <div style="padding:12px 20px;border-right:1px solid #F1F5F9;flex:1;">
        <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.12em;margin-bottom:3px;">Undervalued</div>
        <div style="font-size:20px;font-weight:700;color:#059669;
                    font-family:'IBM Plex Mono',monospace;">{_wl_n_under}</div>
      </div>
      <div style="padding:12px 20px;border-right:1px solid #F1F5F9;flex:1;">
        <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.12em;margin-bottom:3px;">Alerts Triggered</div>
        <div style="font-size:20px;font-weight:700;color:{'#DC2626' if _wl_n_alert else '#94A3B8'};
                    font-family:'IBM Plex Mono',monospace;">{_wl_n_alert}</div>
      </div>
      <div style="padding:12px 20px;flex:1;text-align:right;">
        <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.12em;margin-bottom:3px;">Last updated</div>
        <div style="font-size:13px;font-weight:600;color:#64748B;
                    font-family:'IBM Plex Mono',monospace;">{_wl_now}</div>
      </div>
    </div>
    """)

    # ── Top controls ──────────────────────────────────────────
    _wl_ctrl1, _wl_ctrl2 = st.columns([5, 1])
    with _wl_ctrl2:
        if st.button("🔄 Refresh Prices", key="wl_refresh_all",
                     width='stretch'):
            _wl_fetch_price.clear()
            st.rerun()

    # ── Empty state ───────────────────────────────────────────
    if not _wl_enriched:
        st.html("""
        <div style="text-align:center;padding:48px 24px;background:#F8FAFC;
                    border:2px dashed #E2E8F0;border-radius:12px;margin-top:8px;">
          <div style="font-size:32px;margin-bottom:12px;">📌</div>
          <div style="font-size:15px;font-weight:600;color:#0F172A;margin-bottom:6px;">
            Your watchlist is empty
          </div>
          <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
            Run a stock analysis on the <strong>🔍 Stock Analysis</strong> tab,<br>
            then click <strong>📌 Add to Watchlist</strong> to track it here.
          </div>
        </div>
        """)
    else:
        # ── Cards grid — 3 per row ────────────────────────────
        _WL_COLS = 3
        for _wl_row_start in range(0, len(_wl_enriched), _WL_COLS):
            _wl_row = _wl_enriched[_wl_row_start:_wl_row_start + _WL_COLS]
            _wl_cols = st.columns(_WL_COLS)

            for _wl_col, _w in zip(_wl_cols, _wl_row):
                _tk       = _w["ticker"]
                _mos      = _w["current_mos"]
                _live     = _w["live_price"]
                _added    = _w["added_price"]
                _tgt      = _w["target_price"]
                _thresh   = _w["alert_mos_threshold"]
                _notes_txt = (_w.get("notes") or "").strip()
                _since_added = ((_live - _added) / _added * 100) if _added > 0 else 0.0
                _day_c    = _w["day_chg_pct"]
                _co_name  = (_w.get("company_name") or _tk)[:28]

                # ── Colour scheme by MoS ──────────────────────────
                _alert_triggered = _mos >= _thresh
                if _alert_triggered:
                    _mos_col, _mos_bg, _top_bar = "#185FA5", "#EFF6FF", "#1D4ED8"
                elif _mos > 10:
                    _mos_col, _mos_bg, _top_bar = "#185FA5", "#EFF6FF", "#3B82F6"
                elif _mos > 0:
                    _mos_col, _mos_bg, _top_bar = "#D97706", "#FFFBEB", "#F59E0B"
                else:
                    _mos_col, _mos_bg, _top_bar = "#B45309", "#FFFBEB", "#D97706"

                _since_col = "#059669" if _since_added >= 0 else "#DC2626"
                _since_sym = "▲" if _since_added >= 0 else "▼"
                _day_col   = "#059669" if _day_c >= 0 else "#DC2626"
                _day_sym   = "▲" if _day_c >= 0 else "▼"

                # ── vs Target column ──────────────────────────────
                _vs_tgt_pct = ((_live - _added) / (_tgt - _added) * 100) if (_tgt > _added and _added > 0) else 0.0
                _vs_tgt_pct = max(0.0, min(100.0, _vs_tgt_pct))
                _vs_tgt_txt = f"{_vs_tgt_pct:.0f}% to target"

                # ── Progress bar fill ─────────────────────────────
                _prog_pct   = _vs_tgt_pct
                _prog_color = "#059669" if _prog_pct >= 50 else "#3B82F6"

                # ── Notes snippet ─────────────────────────────────
                _notes_html = (
                    f'<div style="font-size:11px;color:#94A3B8;font-style:italic;'
                    f'margin-top:8px;padding-top:8px;border-top:1px dashed #F1F5F9;'
                    f'line-height:1.5;">"{_notes_txt[:60]}{"…" if len(_notes_txt)>60 else ""}"</div>'
                ) if _notes_txt else ""

                # ── Alert border & pulse ──────────────────────────
                _card_border = "2px solid #F59E0B" if _alert_triggered else "1px solid #E2E8F0"
                _pulse_style = (
                    "animation:wl-pulse 2s ease-in-out infinite;"
                    if _alert_triggered else ""
                )
                _alert_chip = (
                    '<div style="display:inline-flex;align-items:center;gap:4px;'
                    'padding:2px 8px;background:#FEF3C7;border:1px solid #F59E0B;'
                    'border-radius:10px;font-size:10px;font-weight:700;color:#B45309;'
                    'margin-bottom:8px;">🔔 ALERT TRIGGERED</div>'
                    if _alert_triggered else ""
                )

                # ── Sparkline (use mini_sparkline if history available) ─
                _spark_html = ""
                try:
                    import yfinance as _yf_spark
                    _hist = _yf_spark.Ticker(_tk).history(period="7d", interval="1d")
                    if _hist is not None and not _hist.empty and len(_hist) >= 2:
                        _spark_vals = _hist["Close"].dropna().tolist()
                        _spark_html = (
                            '<div style="margin:8px 0 4px;">'
                            + mini_sparkline(_spark_vals, width=80, height=24)
                            + '</div>'
                        )
                except Exception:
                    pass

                _wl_col.html(f"""
                <style>
                @keyframes wl-pulse {{
                  0%,100% {{ box-shadow: 0 2px 8px rgba(245,158,11,0.15); }}
                  50%      {{ box-shadow: 0 4px 20px rgba(245,158,11,0.40); }}
                }}
                .wl-card:hover {{
                  transform: translateY(-2px);
                  box-shadow: 0 8px 24px rgba(15,23,42,0.10) !important;
                }}
                </style>

                <div class="wl-card" style="
                  background:#FFFFFF;
                  border:{_card_border};
                  border-radius:12px;
                  overflow:hidden;
                  margin-bottom:4px;
                  box-shadow:0 2px 8px rgba(15,23,42,0.06);
                  transition:transform .18s ease, box-shadow .18s ease;
                  {_pulse_style}
                ">
                  <!-- Top accent bar -->
                  <div style="height:3px;background:{_top_bar};"></div>

                  <div style="padding:14px 16px 12px;">
                    {_alert_chip}

                    <!-- Header row: Ticker + Price -->
                    <div style="display:flex;justify-content:space-between;
                                align-items:flex-start;margin-bottom:2px;">
                      <div>
                        <div style="font-family:'IBM Plex Mono',monospace;font-size:17px;
                                    font-weight:800;color:#0F172A;letter-spacing:-0.01em;">
                          {_tk}
                        </div>
                        <div style="font-size:11px;color:#94A3B8;margin-top:1px;
                                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                                    max-width:120px;">
                          {_co_name}
                        </div>
                      </div>
                      <div style="text-align:right;">
                        <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;
                                    font-weight:700;color:#0F172A;">
                          {sym}{_live:,.2f}
                        </div>
                        <div style="font-size:11px;font-weight:600;color:{_day_col};">
                          {_day_sym} {abs(_day_c):.2f}%
                        </div>
                      </div>
                    </div>

                    <!-- Sparkline -->
                    {_spark_html}

                    <!-- Metrics row: MoS | Since Added | vs Target -->
                    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;
                                gap:5px;margin:10px 0;">
                      <div style="background:{_mos_bg};border-radius:7px;
                                  padding:7px 6px;text-align:center;">
                        <div style="font-size:9px;color:#94A3B8;text-transform:uppercase;
                                    letter-spacing:0.08em;margin-bottom:2px;">MoS</div>
                        <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                                    font-weight:800;color:{_mos_col};">{_mos:+.1f}%</div>
                      </div>
                      <div style="background:#F8FAFC;border-radius:7px;
                                  padding:7px 6px;text-align:center;">
                        <div style="font-size:9px;color:#94A3B8;text-transform:uppercase;
                                    letter-spacing:0.08em;margin-bottom:2px;">Since Added</div>
                        <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                                    font-weight:700;color:{_since_col};">
                          {_since_sym} {abs(_since_added):.1f}%
                        </div>
                      </div>
                      <div style="background:#EFF6FF;border-radius:7px;
                                  padding:7px 6px;text-align:center;">
                        <div style="font-size:9px;color:#3B82F6;text-transform:uppercase;
                                    letter-spacing:0.08em;margin-bottom:2px;">vs Target</div>
                        <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                                    font-weight:700;color:#1D4ED8;">{_vs_tgt_txt}</div>
                      </div>
                    </div>

                    <!-- Progress bar: journey to target -->
                    <div style="margin-bottom:6px;">
                      <div style="display:flex;justify-content:space-between;
                                  font-size:9px;color:#94A3B8;margin-bottom:3px;">
                        <span>Added {sym}{_added:,.0f}</span>
                        <span>Target {sym}{_tgt:,.0f}</span>
                      </div>
                      <div style="height:5px;background:#F1F5F9;border-radius:3px;overflow:hidden;">
                        <div style="height:100%;width:{_prog_pct:.1f}%;
                                    background:{_prog_color};border-radius:3px;
                                    transition:width .4s ease;"></div>
                      </div>
                    </div>

                    <!-- Alert badge -->
                    <div style="font-size:10px;color:#94A3B8;margin-top:4px;">
                      <span style="padding:1px 7px;background:#F8FAFC;
                                   border:1px solid #E2E8F0;border-radius:8px;
                                   font-family:'IBM Plex Mono',monospace;">
                        Alert: {_thresh:.0f}%
                      </span>
                    </div>

                    <!-- Notes -->
                    {_notes_html}
                  </div>
                </div>
                """)

                # ── Action buttons ────────────────────────────────
                _btn_c1, _btn_c2 = _wl_col.columns(2)
                with _btn_c1:
                    if st.button(
                        "🔍 Analyse", key=f"wl_analyse_{_tk}",
                        width='stretch',
                        help=f"Switch to Stock Analysis and pre-fill {_tk}",
                    ):
                        st.session_state["_prefill_ticker"] = _tk
                        st.rerun()
                with _btn_c2:
                    if st.button(
                        "🗑 Remove", key=f"wl_remove_{_tk}",
                        width='stretch',
                    ):
                        remove_from_watchlist(_tk)
                        _wl_fetch_price.clear()
                        st.rerun()

