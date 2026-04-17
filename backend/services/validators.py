# backend/services/validators.py
# ═══════════════════════════════════════════════════════════════
# DATA QUALITY VALIDATORS
#
# Hard rules + cross-field consistency checks for analysis output.
# Last line of defense before sending data to frontend.
#
# Convention: WACC, terminal_growth, fcf_growth_rate are DECIMALS (0.12).
#             ROE, ROCE are PERCENTAGES (23.5).
#             D/E is RATIO (0.85).
#             MoS is PERCENTAGE (-50 to +200).
#
# Each validation returns a list of issues. Empty list = OK.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("yieldiq.validators")


@dataclass
class ValidationResult:
    ok: bool = True
    severity: str = "ok"  # "ok" | "warning" | "critical"
    issues: list[str] = field(default_factory=list)
    failed_fields: list[str] = field(default_factory=list)


# ── HARD BOUNDS ───────────────────────────────────────────────

BOUNDS = {
    # field: (min, max, severity)
    "wacc":              (0.02, 0.30, "critical"),    # 2%-30%
    "terminal_growth":   (0.0,  0.08, "critical"),    # 0%-8%
    "fcf_growth_rate":   (-0.50, 0.80, "warning"),    # -50% to +80%
    "margin_of_safety":  (-95, 500, "critical"),      # -95% to +500%
    "fair_value_ratio":  (0.20, 5.0, "critical"),     # FV/CMP ratio
    "roe_pct":           (-100, 200, "warning"),      # -100% to +200%
    "roce_pct":          (-100, 200, "warning"),
    "de_ratio":          (0, 20, "warning"),          # 0 to 20
    "score":             (0, 100, "critical"),
    "piotroski":         (0, 9, "critical"),
    "confidence":        (0, 100, "warning"),
    "pe_ratio":          (-200, 500, "warning"),
    "market_cap_inr":    (10e7, 30e12, "critical"),   # ₹10 Cr to ₹30L Cr
}


def _check_bound(name: str, val, result: ValidationResult) -> None:
    """Check a value against BOUNDS. Mutates result in place."""
    if val is None:
        return
    if name not in BOUNDS:
        return
    try:
        v = float(val)
    except (TypeError, ValueError):
        return
    lo, hi, sev = BOUNDS[name]
    if v < lo or v > hi:
        result.ok = False
        result.failed_fields.append(name)
        result.issues.append(f"{name}={v:g} outside bounds [{lo}, {hi}]")
        if sev == "critical":
            result.severity = "critical"
        elif sev == "warning" and result.severity == "ok":
            result.severity = "warning"


def validate_analysis(response) -> ValidationResult:
    """
    Run all validation rules against an AnalysisResponse object.
    Returns ValidationResult with issues found.
    """
    result = ValidationResult()

    if not response:
        result.ok = False
        result.severity = "critical"
        result.issues.append("Response is empty")
        return result

    # Extract fields
    v = getattr(response, "valuation", None)
    q = getattr(response, "quality", None)
    c = getattr(response, "company", None)

    if v:
        _check_bound("wacc", getattr(v, "wacc", None), result)
        _check_bound("terminal_growth", getattr(v, "terminal_growth", None), result)
        _check_bound("fcf_growth_rate", getattr(v, "fcf_growth_rate", None), result)
        _check_bound("margin_of_safety", getattr(v, "margin_of_safety", None), result)
        _check_bound("confidence", getattr(v, "confidence_score", None), result)

        # Fair value vs CMP ratio
        fv = getattr(v, "fair_value", 0) or 0
        cmp_price = getattr(v, "current_price", 0) or 0
        if fv > 0 and cmp_price > 0:
            ratio = fv / cmp_price
            _check_bound("fair_value_ratio", ratio, result)

        # WACC < risk-free rate is impossible (assume India RFR ~6.5%)
        wacc = getattr(v, "wacc", None)
        if wacc is not None and wacc < 0.04:
            result.ok = False
            result.severity = "critical"
            result.issues.append(f"WACC {wacc*100:.2f}% below risk-free rate")
            result.failed_fields.append("wacc")

    if q:
        _check_bound("roe_pct", getattr(q, "roe", None), result)
        _check_bound("roce_pct", getattr(q, "roce", None), result)
        _check_bound("de_ratio", getattr(q, "de_ratio", None), result)
        _check_bound("score", getattr(q, "yieldiq_score", None), result)
        _check_bound("piotroski", getattr(q, "piotroski_score", None), result)

    if c:
        _check_bound("market_cap_inr", getattr(c, "market_cap", None), result)

    # ── CROSS-FIELD CONSISTENCY ───────────────────────────────

    if v and q:
        moat = getattr(q, "moat", "") or ""
        roe = getattr(q, "roe", None)
        if moat == "Wide" and roe is not None and roe < 8:
            result.issues.append(
                f"Wide moat with ROE {roe:.1f}% — inconsistent (Wide moat usually has ROE >12%)"
            )
            if result.severity == "ok":
                result.severity = "warning"

        piotroski = getattr(q, "piotroski_score", None)
        de = getattr(q, "de_ratio", None)
        if piotroski and piotroski >= 7 and de and de > 2:
            result.issues.append(
                f"High Piotroski ({piotroski}/9) with D/E {de:.2f} — review"
            )

        fv = getattr(v, "fair_value", 0) or 0
        cmp_price = getattr(v, "current_price", 0) or 0
        confidence = getattr(v, "confidence_score", 0) or 0
        if fv > 0 and cmp_price > 0 and confidence > 70:
            ratio = fv / cmp_price
            if ratio > 3 or ratio < 0.5:
                result.issues.append(
                    f"FV/CMP ratio {ratio:.1f}x with confidence {confidence}% — review"
                )

        # FCF growth assumption sanity
        fcf_growth = getattr(v, "fcf_growth_rate", None)
        if fcf_growth is not None and fcf_growth > 0.25:
            result.issues.append(
                f"FCF growth assumption {fcf_growth*100:.1f}% sustained 10y — historically rare"
            )

    return result


def log_validation(ticker: str, result: ValidationResult) -> None:
    """Log validation issues at appropriate level."""
    if result.ok and not result.issues:
        return
    if result.severity == "critical":
        logger.error(
            "VALIDATION CRITICAL [%s]: %d issues, fields=%s | %s",
            ticker, len(result.issues), result.failed_fields, "; ".join(result.issues)
        )
    else:
        logger.warning(
            "VALIDATION WARNING [%s]: %d issues | %s",
            ticker, len(result.issues), "; ".join(result.issues)
        )
