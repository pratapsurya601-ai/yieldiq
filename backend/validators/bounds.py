# backend/validators/bounds.py
# ═══════════════════════════════════════════════════════════════
# SINGLE SOURCE OF TRUTH for field bounds.
#
# YieldIQ dual convention (do not "unify" without a CACHE_VERSION bump
# and a coordinated frontend change — see CACHE_VERSION discipline):
#   - rates (wacc, terminal_growth, fcf_growth_rate, cagr) are DECIMALS
#   - ROE/ROCE/margin_of_safety are PERCENT
#   - de_ratio, current_ratio, asset_turnover are RATIOS
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

# field -> (min, max, severity)
BOUNDS: dict[str, tuple[float, float, str]] = {
    # ── Return metrics (percent) ──────────────────────────────
    "roe":                (-100, 200,  "warning"),    # ROE percent
    "roe_pct":            (-100, 200,  "warning"),
    # FIX2: tightened upper bound from 200 → 100. ROCE > 100% means
    # capital employed is tiny relative to EBIT — almost always a
    # data-quality issue (unit mixup, missing balance sheet) rather
    # than a real signal. Negative ROCE is genuine (loss-making) so
    # we keep the floor at -100.
    "roce":               (-100, 100,  "warning"),    # ROCE percent
    "roce_pct":           (-100, 100,  "warning"),

    # ── Cost of capital (decimal) ─────────────────────────────
    "wacc":               (0.02, 0.30, "critical"),   # 2%-30%
    "terminal_growth":    (0.0,  0.08, "critical"),   # 0%-8%
    "fcf_growth_rate":    (-0.50, 0.80, "warning"),   # -50% to +80%
    "risk_free_rate":     (0.01, 0.12, "warning"),

    # ── Leverage & liquidity ──────────────────────────────────
    "de_ratio":           (0,    20,   "warning"),    # D/E ratio
    "debt_ebitda":        (-5,   50,   "warning"),    # D/EBITDA ratio
    "interest_coverage":  (-100, 1000, "warning"),    # EBIT/Interest
    "current_ratio":      (0,    20,   "warning"),    # CA/CL

    # ── Valuation multiples ───────────────────────────────────
    "pe_ratio":           (-200, 500,  "warning"),
    "pb_ratio":           (0.01, 100,  "warning"),
    # FIX2: tightened from (-100, 500, warning) to (-100, 200, critical).
    # PR1 (2026-04-19): floor moved to 0.5 — values exactly 0.0 (sentinel
    # for "EBITDA was zero / negative, ratio is undefined") were leaking
    # to the UI as "0.0×". Fail-closed: if you really hit 0.5×, the
    # business has near-zero enterprise value relative to EBITDA which
    # is itself a data-quality red flag worth surfacing.
    "ev_ebitda":          (0.5,  200,  "critical"),
    "ps_ratio":           (0,    100,  "warning"),

    # ── Valuation outputs ─────────────────────────────────────
    "fair_value":         (0.01, 1e7,  "critical"),   # INR per share
    "current_price":      (0.01, 1e7,  "critical"),
    "fair_value_ratio":   (0.20, 5.0,  "critical"),   # FV/CMP
    "margin_of_safety":   (-95,  500,  "critical"),   # percent
    # PR1 additions ---------------------------------------------
    # Tighter MoS gate for the response payload (the field name in the
    # response is `margin_of_safety` in percent; `mos_pct` is the
    # canonical name in dict-based ingestion records). ±150% catches
    # impossible blended-FV cases without triggering on the legitimate
    # +95% cap from the existing margin_of_safety bound.
    "mos_pct":            (-150, 150,  "critical"),
    # Warn-level FV/CMP ratio inside the existing critical band so a
    # gentler trigger surfaces in dashboards before the hard 0.20-5.0
    # cutoff fires. Anything outside 0.4-2.5x deserves human review.
    "fair_value_to_price_ratio": (0.4, 2.5, "warning"),

    # ── Scores ────────────────────────────────────────────────
    "score":              (0,    100,  "critical"),
    "yieldiq_score":      (0,    100,  "critical"),
    "piotroski":          (0,    9,    "critical"),
    "piotroski_score":    (0,    9,    "critical"),
    "confidence":         (0,    100,  "warning"),

    # ── Size ──────────────────────────────────────────────────
    "market_cap":         (10e7, 30e12, "critical"),  # INR 10 Cr to 30L Cr
    "market_cap_inr":     (10e7, 30e12, "critical"),

    # ── Growth (decimal) ──────────────────────────────────────
    # PR1: tightened from (-0.50, 1.50, warning) to (-0.40, 0.40, critical).
    # Established large-caps with sustained ±40%+ 3y revenue CAGR are
    # essentially nonexistent in our covered universe; values outside
    # this band are almost always a base-period bug (post-IPO partial
    # year, demerger, units mismatch). Fail-closed.
    "revenue_cagr_3y":    (-0.40, 0.40, "critical"),
    "revenue_cagr_5y":    (-0.50, 1.00, "warning"),
    "fcf_growth":         (-0.90, 2.00, "warning"),

    # ── Efficiency ────────────────────────────────────────────
    "asset_turnover":     (0,    10.0, "warning"),
}


# Forbidden sentinel values. PR1: ratios_service used to emit `0.0` as a
# silent "could not compute" sentinel for ROCE; the UI then rendered "0.0%"
# which is materially different from "—". Treat exact-0 as invalid for these
# fields so they fail-closed to NULL/render-dash. Add fields here whose
# computation pipeline is known to use 0 as an undefined-sentinel.
FORBIDDEN_VALUES: dict[str, tuple[float, ...]] = {
    "roce":     (0.0,),
    "roce_pct": (0.0,),
}


def validate_field(name: str, value) -> tuple[bool, str | None]:
    """Return (is_valid, error_or_None) for a single field."""
    if name not in BOUNDS:
        return True, None  # unknown field, skip
    if value is None:
        return True, None  # required-ness is the caller's concern
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, f"{name} must be numeric, got {type(value).__name__}"
    if v != v:  # NaN check
        return False, f"{name} is NaN"
    forbidden = FORBIDDEN_VALUES.get(name)
    if forbidden is not None and v in forbidden:
        return False, f"{name}={v:g} is a forbidden sentinel (treat as NULL)"
    lo, hi, _sev = BOUNDS[name]
    if v < lo or v > hi:
        return False, f"{name}={v:g} outside bounds [{lo}, {hi}]"
    return True, None


def validate_record(record: dict) -> list[str]:
    """Return list of validation errors for a record dict. Empty = valid."""
    errors: list[str] = []
    for field, value in record.items():
        ok, err = validate_field(field, value)
        if not ok and err is not None:
            errors.append(err)
    return errors


def severity_for(field: str) -> str:
    """Return the bound severity for a field, defaulting to 'warning'."""
    if field in BOUNDS:
        return BOUNDS[field][2]
    return "warning"
