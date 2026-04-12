# dashboard/utils/portfolio_health.py
# ═══════════════════════════════════════════════════════════════
# Portfolio Health Score (0-100)
# Weekly score driving habit loop — like a fitness app step count.
# Used in Portfolio tab header and weekly notification.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations


def calculate_portfolio_health(holdings: list[dict]) -> dict:
    """
    Calculate a portfolio health score (0-100).

    holdings: list of dicts with keys:
      ticker, shares, avg_buy_price, current_price,
      yieldiq_score, mos, moat, confidence, red_flags

    Returns dict with score, grade, summary, issues, strengths, etc.
    """
    if not holdings:
        return {
            "score": 0, "grade": "F",
            "summary": "No holdings to score. Add stocks to your portfolio.",
            "issues": ["Portfolio is empty"],
            "strengths": [],
            "overvalued_count": 0,
            "undervalued_count": 0,
            "danger_positions": [],
            "concentration_warning": None,
        }

    # ── Calculate position values ──────────────────────────────
    _total_value = 0.0
    _position_values = []
    for h in holdings:
        _shares = float(h.get("shares", 1) or 1)
        _price = float(h.get("current_price", h.get("avg_buy_price", 0)) or 0)
        _val = _shares * _price
        _position_values.append(_val)
        _total_value += _val

    if _total_value <= 0:
        _total_value = 1.0  # avoid division by zero
        _weights = [1.0 / len(holdings)] * len(holdings)
    else:
        _weights = [v / _total_value for v in _position_values]

    # ── 1. Average YieldIQ Score (30pts max) ───────────────────
    _weighted_score = sum(
        float(h.get("yieldiq_score", 50) or 50) * w
        for h, w in zip(holdings, _weights)
    )
    if _weighted_score > 75:
        _score_pts = 30
    elif _weighted_score > 60:
        _score_pts = 20
    elif _weighted_score > 45:
        _score_pts = 12
    else:
        _score_pts = 5

    # ── 2. Overvaluation exposure (25pts max) ──────────────────
    _overvalued_value = sum(
        v for h, v in zip(holdings, _position_values)
        if float(h.get("mos", 0) or 0) < -5
    )
    _overvalued_pct = (_overvalued_value / _total_value) * 100
    _overvalued_count = sum(1 for h in holdings if float(h.get("mos", 0) or 0) < -5)
    _undervalued_count = sum(1 for h in holdings if float(h.get("mos", 0) or 0) > 5)

    if _overvalued_pct < 20:
        _oval_pts = 25
    elif _overvalued_pct < 40:
        _oval_pts = 15
    elif _overvalued_pct < 60:
        _oval_pts = 8
    else:
        _oval_pts = 2

    # ── 3. Red flag exposure (20pts max) ───────────────────────
    _total_flags = 0
    _danger_tickers = []
    for h in holdings:
        _flags = h.get("red_flags", []) or []
        if isinstance(_flags, int):
            _n = _flags
        elif isinstance(_flags, (list, tuple)):
            _n = len(_flags)
        else:
            _n = 0
        _total_flags += _n
        if _n > 0:
            _danger_tickers.append(str(h.get("ticker", "?")))

    if _total_flags == 0:
        _flag_pts = 20
    elif _total_flags <= 2:
        _flag_pts = 14
    elif _total_flags <= 5:
        _flag_pts = 7
    else:
        _flag_pts = 2

    # ── 4. Concentration risk (15pts max) ──────────────────────
    _max_weight = max(_weights) * 100 if _weights else 0
    _max_ticker = holdings[_weights.index(max(_weights))].get("ticker", "?") if _weights else "?"

    if _max_weight <= 30:
        _conc_pts = 15
        _conc_warning = None
    elif _max_weight <= 40:
        _conc_pts = 10
        _conc_warning = f"{_max_ticker} is {_max_weight:.0f}% of your portfolio — consider rebalancing"
    elif _max_weight <= 60:
        _conc_pts = 5
        _conc_warning = f"{_max_ticker} at {_max_weight:.0f}% is a significant concentration risk"
    else:
        _conc_pts = 1
        _conc_warning = f"{_max_ticker} at {_max_weight:.0f}% — very high concentration risk"

    # ── 5. Diversification (10pts max) ─────────────────────────
    _sectors = set()
    for h in holdings:
        _s = h.get("sector", h.get("sector_name", "Unknown")) or "Unknown"
        _sectors.add(_s)

    if len(_sectors) >= 3:
        _div_pts = 10
    elif len(_sectors) == 2:
        _div_pts = 6
    else:
        _div_pts = 2

    # ── Total ──────────────────────────────────────────────────
    _total = _score_pts + _oval_pts + _flag_pts + _conc_pts + _div_pts
    _total = max(0, min(100, _total))

    # Grade
    if _total >= 85:
        _grade = "A"
    elif _total >= 70:
        _grade = "B"
    elif _total >= 55:
        _grade = "C"
    elif _total >= 40:
        _grade = "D"
    else:
        _grade = "F"

    # Issues and strengths
    _issues = []
    _strengths = []

    if _overvalued_count > 0:
        _issues.append(f"{_overvalued_count} position{'s' if _overvalued_count > 1 else ''} now overvalued")
    if _total_flags > 0:
        _issues.append(f"{_total_flags} red flag{'s' if _total_flags > 1 else ''} detected")
    if _conc_warning:
        _issues.append(_conc_warning)
    if len(_sectors) < 3:
        _issues.append(f"Low diversification — only {len(_sectors)} sector{'s' if len(_sectors) > 1 else ''}")

    if _undervalued_count > 0:
        _strengths.append(f"{_undervalued_count} position{'s' if _undervalued_count > 1 else ''} undervalued by our model")
    if _weighted_score > 65:
        _strengths.append(f"Strong average quality score ({_weighted_score:.0f})")
    if _total_flags == 0:
        _strengths.append("No red flags across any holding")
    if len(_sectors) >= 4:
        _strengths.append(f"Well diversified across {len(_sectors)} sectors")

    # Summary
    if _total >= 85:
        _summary = "Excellent portfolio health — well diversified with strong fundamentals."
    elif _total >= 70:
        _summary = f"Good overall. {_issues[0] if _issues else 'Minor improvements possible.'}"
    elif _total >= 55:
        _summary = f"Mixed signals. {_issues[0] if _issues else 'Review recommended.'}"
    elif _total >= 40:
        _summary = f"Below average. {_issues[0] if _issues else 'Several areas need attention.'}"
    else:
        _summary = f"Needs attention. {_issues[0] if _issues else 'Significant risk exposure.'}"

    return {
        "score": _total,
        "grade": _grade,
        "summary": _summary,
        "issues": _issues,
        "strengths": _strengths,
        "overvalued_count": _overvalued_count,
        "undervalued_count": _undervalued_count,
        "danger_positions": _danger_tickers,
        "concentration_warning": _conc_warning,
    }


def render_portfolio_health_header(health: dict) -> None:
    """Render portfolio health score as a styled header in Streamlit."""
    import streamlit as st

    _score = health["score"]
    _grade = health["grade"]
    _summary = health["summary"]

    # Color by grade
    if _grade in ("A",):
        _color, _bg = "#059669", "#F0FDF4"
    elif _grade in ("B",):
        _color, _bg = "#1D4ED8", "#EFF6FF"
    elif _grade in ("C",):
        _color, _bg = "#D97706", "#FFFBEB"
    else:
        _color, _bg = "#DC2626", "#FEF2F2"

    _bar_pct = max(2, min(100, _score))

    st.html(f"""
    <div style="background:{_bg};border:1px solid {_color}20;border-radius:14px;
                padding:16px 20px;margin-bottom:16px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:10px;">
        <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.1em;">Portfolio health</div>
        <div style="font-size:28px;font-weight:900;color:{_color};
                    font-family:IBM Plex Mono,monospace;">{_score}</div>
        <div style="font-size:12px;color:#94A3B8;">/ 100</div>
        <div style="background:{_color};color:white;font-size:11px;font-weight:700;
                    padding:2px 10px;border-radius:8px;">Grade: {_grade}</div>
      </div>
      <div style="background:#E2E8F0;border-radius:6px;height:8px;margin-bottom:10px;">
        <div style="background:{_color};border-radius:6px;height:8px;width:{_bar_pct}%;
                    transition:width 0.3s;"></div>
      </div>
      <div style="font-size:12px;color:#475569;">{_summary}</div>
    </div>
    """)

    # Expandable details
    if health["issues"] or health["strengths"]:
        with st.expander("See details"):
            if health["issues"]:
                for issue in health["issues"]:
                    st.html(f'<div style="font-size:12px;color:#DC2626;margin-bottom:4px;">⚠ {issue}</div>')
            if health["strengths"]:
                for strength in health["strengths"]:
                    st.html(f'<div style="font-size:12px;color:#059669;margin-bottom:4px;">✓ {strength}</div>')
