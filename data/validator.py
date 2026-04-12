# data/validator.py
# ═══════════════════════════════════════════════════════════════
# NSE Data Validation Layer
# Validates fetched stock data quality before running DCF model.
# Returns confidence level, warnings, and whether to show DCF.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
from dataclasses import dataclass, field
import time


@dataclass
class ValidationResult:
    """Result of data quality validation."""
    confidence: str = "high"          # "high" | "medium" | "low" | "unusable"
    confidence_score: int = 100       # 0-100
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    show_dcf: bool = True             # False = don't show DCF, data too poor
    ui_message: str = ""              # Warning to display in UI
    data_age_seconds: float = 0.0     # How old the data is


def validate_stock_data(ticker: str, raw_data: dict) -> ValidationResult:
    """
    Validate fetched stock data quality.
    Returns ValidationResult with confidence level and issues found.

    Does NOT block — returns result, lets UI decide what to show.
    """
    result = ValidationResult()
    _score = 100

    if not raw_data:
        return ValidationResult(
            confidence="unusable", confidence_score=0,
            issues=["No data returned"],
            show_dcf=False,
            ui_message=f"Could not fetch data for {ticker}. Please check the ticker symbol."
        )

    # ── 1. Data freshness ──────────────────────────────────────
    _fetched_at = raw_data.get("_fetched_at", 0)
    if _fetched_at:
        _age = time.time() - _fetched_at
        result.data_age_seconds = _age
        if _age > 86400:  # > 24 hours
            result.warnings.append("Data is more than 24 hours old")
            _score -= 10
        if _age > 604800:  # > 7 days
            result.issues.append("Data is more than 7 days old — may be stale")
            _score -= 20

    # ── 2. Price data ──────────────────────────────────────────
    _price = raw_data.get("price", 0) or 0
    if _price <= 0:
        result.issues.append("No price data available")
        _score -= 30
        result.show_dcf = False

    # ── 3. Financial statements ────────────────────────────────
    _income_df = raw_data.get("income_df")
    _cf_df = raw_data.get("cf_df")

    _has_income = _income_df is not None and hasattr(_income_df, 'empty') and not _income_df.empty
    _has_cf = _cf_df is not None and hasattr(_cf_df, 'empty') and not _cf_df.empty

    if not _has_income:
        result.issues.append("Income statement not available")
        _score -= 25
    elif hasattr(_income_df, '__len__') and len(_income_df) < 3:
        result.warnings.append(f"Only {len(_income_df)} years of income data (ideally 5+)")
        _score -= 10

    if not _has_cf:
        result.issues.append("Cash flow statement not available")
        _score -= 25
        result.show_dcf = False
    elif hasattr(_cf_df, '__len__') and len(_cf_df) < 3:
        result.warnings.append(f"Only {len(_cf_df)} years of cash flow data (ideally 5+)")
        _score -= 10

    # ── 4. Key metrics ─────────────────────────────────────────
    _shares = raw_data.get("shares", 0) or 0
    if _shares <= 0:
        result.issues.append("Shares outstanding not available")
        _score -= 20
        result.show_dcf = False

    _total_debt = raw_data.get("total_debt")
    _total_cash = raw_data.get("total_cash")
    if _total_debt is None and _total_cash is None:
        result.warnings.append("Balance sheet data (debt/cash) not available")
        _score -= 10

    # ── 5. FCF data quality ────────────────────────────────────
    _fcf = raw_data.get("yahoo_fcf_ttm", 0) or 0
    if _fcf == 0 and _has_cf:
        result.warnings.append("TTM free cash flow is zero — model may undervalue")
        _score -= 5

    # ── 6. NSE-specific checks (.NS and .BO tickers) ──────────
    _is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")
    if _is_indian:
        _native_ccy = raw_data.get("native_ccy", "")
        _fin_mult = raw_data.get("fin_multiplier", 1.0)

        # Check if financials appear to be in wrong currency
        if _native_ccy and _native_ccy not in ("INR", ""):
            result.warnings.append(
                f"Indian stock reporting in {_native_ccy} — currency mismatch possible"
            )
            _score -= 10

        # Check for Crore/Lakh scaling issues
        if _fin_mult and _fin_mult > 1:
            pass  # Expected — financials scaled correctly
        elif _has_income:
            # If revenue is very small for an Indian listed company, might be scaling issue
            try:
                import pandas as pd
                if hasattr(_income_df, 'iloc'):
                    _rev_col = None
                    for col in _income_df.columns:
                        if "revenue" in str(col).lower() or "total" in str(col).lower():
                            _rev_col = col
                            break
                    if _rev_col:
                        _latest_rev = abs(float(_income_df[_rev_col].iloc[0] or 0))
                        if 0 < _latest_rev < 1e6:  # Less than 10 Lakh — suspiciously small
                            result.warnings.append(
                                "Revenue appears very small — possible scaling issue"
                            )
                            _score -= 15
            except Exception:
                pass

    # ── 7. Company name sanity check ───────────────────────────
    _company = raw_data.get("company_name", "")
    if not _company or _company == ticker:
        result.warnings.append("Company name not available from data provider")
        _score -= 5

    # ── Compute final confidence ───────────────────────────────
    _score = max(0, min(100, _score))
    result.confidence_score = _score

    if _score >= 80:
        result.confidence = "high"
    elif _score >= 60:
        result.confidence = "medium"
    elif _score >= 40:
        result.confidence = "low"
    else:
        result.confidence = "unusable"
        result.show_dcf = False

    # Build UI message
    if result.confidence == "unusable":
        result.ui_message = (
            f"Data quality for {ticker} is too low for a reliable DCF analysis. "
            f"Issues: {'; '.join(result.issues[:3])}"
        )
    elif result.confidence == "low":
        result.ui_message = (
            f"Data quality for {ticker} is limited — analysis results may be less reliable. "
            f"{result.warnings[0] if result.warnings else ''}"
        )
    elif result.confidence == "medium" and result.warnings:
        result.ui_message = result.warnings[0]

    return result


def get_confidence_badge(validation: ValidationResult) -> str:
    """Return HTML badge for data confidence level."""
    _colors = {
        "high":     ("#185FA5", "#EFF6FF", "High confidence"),
        "medium":   ("#D97706", "#FFFBEB", "Medium confidence"),
        "low":      ("#DC2626", "#FEF2F2", "Low confidence"),
        "unusable": ("#991B1B", "#FEF2F2", "Data unavailable"),
    }
    _text_c, _bg_c, _label = _colors.get(validation.confidence, _colors["medium"])

    return (
        f'<span style="display:inline-block;background:{_bg_c};color:{_text_c};'
        f'font-size:10px;font-weight:700;padding:2px 10px;border-radius:8px;'
        f'margin-bottom:8px;">'
        f'Data: {_label} ({validation.confidence_score}/100)</span>'
    )


def render_partial_analysis(ticker: str, raw_data: dict) -> None:
    """
    Show whatever data IS available when full DCF is not possible.
    Never shows empty screens or raw errors.
    """
    import streamlit as st

    _display = ticker.replace(".NS", "").replace(".BO", "")
    _company = raw_data.get("company_name", _display) or _display
    _price = raw_data.get("price", 0) or 0
    _sector = raw_data.get("sector_name", "") or ""

    st.html(f"""
    <div style="text-align:center;padding:20px 0 16px;">
      <div style="font-size:22px;font-weight:800;color:#0F172A;margin-bottom:4px;">
        {_company}</div>
      <div style="font-size:12px;color:#94A3B8;">{_display} · {_sector}</div>
    </div>
    """)

    if _price > 0:
        _pe = raw_data.get("forward_pe") or raw_data.get("trailing_pe") or 0
        _dy = raw_data.get("dividend_yield") or raw_data.get("fh_div_yield") or 0
        _hi52 = raw_data.get("fh_52w_high", 0) or 0
        _lo52 = raw_data.get("fh_52w_low", 0) or 0
        _beta = raw_data.get("fh_beta", 0) or 0

        _metrics = []
        _metrics.append(("Price", f"₹{_price:,.2f}" if ticker.endswith((".NS", ".BO")) else f"${_price:,.2f}"))
        if _pe and 0 < _pe < 500:
            _metrics.append(("P/E", f"{_pe:.1f}x"))
        if _dy and _dy > 0:
            _dy_pct = _dy * 100 if _dy < 1 else _dy
            _metrics.append(("Div Yield", f"{_dy_pct:.1f}%"))
        if _beta and _beta > 0:
            _metrics.append(("Beta", f"{_beta:.2f}"))

        _cols = st.columns(min(len(_metrics), 4))
        for i, (label, value) in enumerate(_metrics[:4]):
            with _cols[i]:
                st.html(f"""
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
                            padding:12px;text-align:center;">
                  <div style="font-size:10px;color:#94A3B8;font-weight:700;text-transform:uppercase;
                              letter-spacing:0.06em;margin-bottom:4px;">{label}</div>
                  <div style="font-size:18px;font-weight:700;color:#0F172A;
                              font-family:IBM Plex Mono,monospace;">{value}</div>
                </div>
                """)

        if _hi52 > 0 and _lo52 > 0:
            _range_pct = ((_price - _lo52) / (_hi52 - _lo52) * 100) if _hi52 > _lo52 else 50
            st.html(f"""
            <div style="margin:16px 0;padding:12px 16px;background:#F8FAFC;
                        border:1px solid #E2E8F0;border-radius:10px;">
              <div style="font-size:10px;color:#94A3B8;font-weight:700;margin-bottom:8px;">
                52-WEEK RANGE</div>
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:11px;color:#64748B;">₹{_lo52:,.0f}</span>
                <div style="flex:1;height:6px;background:#E2E8F0;border-radius:3px;">
                  <div style="height:100%;width:{_range_pct:.0f}%;background:#1D4ED8;
                              border-radius:3px;"></div>
                </div>
                <span style="font-size:11px;color:#64748B;">₹{_hi52:,.0f}</span>
              </div>
            </div>
            """)
    else:
        st.html("""
        <div style="text-align:center;padding:20px;color:#94A3B8;font-size:14px;">
          Price data unavailable for this ticker.
        </div>
        """)

    st.html("""
    <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:10px;
                padding:14px 16px;margin-top:16px;">
      <div style="font-size:12px;color:#92400E;line-height:1.6;">
        Full DCF analysis is not available for this stock due to limited financial data.
        The metrics shown above are based on available market data only.
        Try a different ticker or check back later when more data becomes available.
      </div>
    </div>
    """)
