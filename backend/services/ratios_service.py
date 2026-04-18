# backend/services/ratios_service.py
# ═══════════════════════════════════════════════════════════════
# Canonical formulas for the quality-and-valuation ratios surfaced
# on the fair-value page. Each function returns `None` on bad input
# rather than raising — callers pipe None through to the frontend
# which renders "—".
#
# Units (matches ValuationOutput / QualityOutput):
#   ROCE, ROA, ROE         -> PERCENT (23.5 for 23.5%)
#   revenue CAGR           -> DECIMAL (0.124 for 12.4%)
#   EV/EBITDA, D/EBITDA,   -> RATIO
#   Current, Asset T/O     -> RATIO
#   Interest coverage      -> RATIO (times)
#
# NOTE: The existing in-flight ROCE computation in analysis_service.py
# uses `ebit / total_assets` (technically ROA). Changing that formula
# is a semantic change for every existing stock and would require a
# coordinated CACHE_VERSION bump per the discipline rules. The
# `compute_roce` in this module uses the textbook capital-employed
# denominator and is intentionally unwired until that rebaseline.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Sequence


def _num(v):
    if v is None:
        return None
    try:
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def compute_roce(ebit, total_assets, current_liabilities) -> float | None:
    """ROCE = EBIT / (Total Assets − Current Liabilities). Returns PERCENT.

    Non-positive EBIT → None. A genuine loss-making company's negative
    ROCE is technically computable, but it's more useful to show "—"
    in the UI than a precise-looking red "-12.3% Weak" — users
    consistently misread the latter as 'healthy company losing money'
    rather than 'data unavailable / deep distress'. Callers that want
    the signed value can compute it themselves.
    """
    _ebit = _num(ebit)
    _ta = _num(total_assets)
    _cl = _num(current_liabilities)
    if _ebit is None or _ebit <= 0 or _ta is None or _cl is None:
        return None
    cap_employed = _ta - _cl
    if cap_employed <= 0:
        return None
    return round(_ebit / cap_employed * 100.0, 1)


def compute_ev_ebitda(market_cap, total_debt, total_cash, ebitda) -> float | None:
    """Enterprise-value multiple. Returns ratio (×)."""
    _mc = _num(market_cap)
    _td = _num(total_debt) or 0.0
    _tc = _num(total_cash) or 0.0
    _eb = _num(ebitda)
    if _mc is None or _eb is None or _eb <= 0:
        return None
    ev = _mc + _td - _tc
    return round(ev / _eb, 1)


def compute_debt_to_ebitda(total_debt, ebitda) -> float | None:
    """Debt / EBITDA. Returns ratio (×)."""
    _td = _num(total_debt)
    _eb = _num(ebitda)
    if _td is None or _eb is None or _eb <= 0:
        return None
    return round(_td / _eb, 1)


def compute_interest_coverage(ebit, interest_expense) -> float | None:
    """EBIT / Interest Expense. Returns ratio (×)."""
    _ebit = _num(ebit)
    _ie = _num(interest_expense)
    if _ebit is None or _ie is None or _ie <= 0:
        return None
    return round(_ebit / _ie, 1)


def compute_current_ratio(current_assets, current_liabilities) -> float | None:
    """Current Assets / Current Liabilities. Returns ratio (×)."""
    _ca = _num(current_assets)
    _cl = _num(current_liabilities)
    if _ca is None or _cl is None or _cl <= 0:
        return None
    return round(_ca / _cl, 2)


def compute_asset_turnover(revenue, total_assets) -> float | None:
    """Revenue / Total Assets. Returns ratio (×)."""
    _rev = _num(revenue)
    _ta = _num(total_assets)
    if _rev is None or _ta is None or _ta <= 0:
        return None
    return round(_rev / _ta, 2)


def compute_revenue_cagr(revenues: Sequence[float], years: int) -> float | None:
    """
    revenues: iterable with the LATEST value LAST (chronological).
    Returns DECIMAL CAGR (0.124 = 12.4%) or None when insufficient data.
    """
    if revenues is None:
        return None
    try:
        series = [float(r) for r in revenues if r is not None]
    except (TypeError, ValueError):
        return None
    if len(series) <= years:
        return None
    start = series[-years - 1]
    end = series[-1]
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return round((end / start) ** (1.0 / years) - 1.0, 4)
