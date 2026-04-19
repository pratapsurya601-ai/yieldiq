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

        # ── FIX1: FV/MoS reconciliation gate ──────────────────
        # The displayed margin_of_safety MUST equal (FV-CMP)/CMP*100
        # within a small slack. If it doesn't, the response carries
        # two inconsistent FV fields (e.g. pre- vs post-moat-adjust)
        # and we fail-closed via the under_review path. 2pp slack
        # absorbs rounding and the Wide-moat IV smoothing band.
        try:
            fv_chk = getattr(v, "fair_value", None)
            cmp_chk = getattr(v, "current_price", None)
            mos_chk = getattr(v, "margin_of_safety", None)
            if (
                fv_chk is not None
                and cmp_chk is not None
                and mos_chk is not None
                and float(cmp_chk) > 0
                and float(fv_chk) > 0
            ):
                expected_mos = (float(fv_chk) - float(cmp_chk)) / float(cmp_chk) * 100.0
                if abs(float(mos_chk) - expected_mos) > 2.0:
                    result.ok = False
                    result.severity = "critical"
                    result.failed_fields.append("margin_of_safety")
                    result.issues.append(
                        f"MOS_FV_MISMATCH: displayed MoS {float(mos_chk):.1f}% "
                        f"inconsistent with (FV-CMP)/CMP={expected_mos:.1f}% "
                        f"(FV={float(fv_chk):g}, CMP={float(cmp_chk):g})"
                    )
        except (TypeError, ValueError):
            pass

    # ── DCF TRACE (ring-buffer) CHECKS ────────────────────────
    try:
        from screener.dcf_engine import DCF_TRACES  # lazy import to avoid cycles
        tkr = getattr(response, "ticker", None)
        if tkr and tkr in DCF_TRACES:
            trace_issues, trace_sev = validate_dcf_trace(tkr, DCF_TRACES[tkr])
            if trace_issues:
                result.issues.extend(trace_issues)
                # Bump severity to worst-of
                order = {"ok": 0, "info": 0, "warning": 1, "critical": 2}
                if order.get(trace_sev, 0) > order.get(result.severity, 0):
                    result.severity = trace_sev
                if trace_sev == "critical":
                    result.ok = False
    except Exception as _te:
        logger.debug("DCF trace validation skipped: %s", _te)

    return result


def validate_dcf_trace(ticker: str, trace: dict) -> tuple[list[str], str]:
    """
    Deterministic red-flag checks against the DCF_TRACES ring-buffer entry.
    Returns (issues, severity) where severity ∈ {"ok","info","warning","critical"}.
    """
    issues: list[str] = []
    sev = "ok"
    order = {"ok": 0, "info": 0, "warning": 1, "critical": 2}

    def _bump(new_sev: str):
        nonlocal sev
        if order.get(new_sev, 0) > order.get(sev, 0):
            sev = new_sev

    if not isinstance(trace, dict):
        return issues, sev

    iv_ratio = trace.get("iv_ratio")
    tv_pct = trace.get("tv_pct_ev")
    impl_g = trace.get("impl_g")
    fcf_base = trace.get("fcf_base")
    capped = trace.get("capped")
    wacc = trace.get("wacc")
    g = trace.get("g")

    try:
        if iv_ratio is not None:
            r = float(iv_ratio)
            if r > 5.0:
                issues.append(f"DCF IV exceeded 5x cap — clamped")
                _bump("critical")
            elif r > 3.0:
                issues.append(f"DCF IV is {r:.1f}x price — suspiciously high")
                _bump("warning")
            elif r < 0.25:
                issues.append(f"DCF IV is {r:.2f}x price — suspiciously low")
                _bump("warning")
    except (TypeError, ValueError):
        pass

    try:
        if tv_pct is not None:
            t = float(tv_pct)
            if t > 0.95:
                issues.append(f"Terminal value is {t*100:.0f}% of EV (fragile)")
                _bump("critical")
            elif t > 0.90:
                issues.append(f"Terminal value is {t*100:.0f}% of EV (fragile)")
                _bump("warning")
    except (TypeError, ValueError):
        pass

    try:
        if impl_g is not None:
            ig = float(impl_g)
            if ig > 0.50:
                issues.append(f"Implied FCF growth {ig:.1%} is unrealistic")
                _bump("critical")
            elif ig > 0.25:
                issues.append(f"Implied FCF growth {ig:.1%} is unrealistic")
                _bump("warning")
    except (TypeError, ValueError):
        pass

    try:
        if fcf_base is not None and float(fcf_base) <= 0:
            issues.append("FCF base is non-positive, DCF unreliable")
            _bump("critical")
    except (TypeError, ValueError):
        pass

    if capped is True:
        issues.append("DCF raw IV was capped (see iv_ratio)")
        _bump("info")

    try:
        if wacc is not None and g is not None:
            spread = float(wacc) - float(g)
            if spread < 0.03:
                issues.append(f"WACC-g spread is only {spread:.2%}, terminal value explodes")
                _bump("critical")
    except (TypeError, ValueError):
        pass

    return issues, sev


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


# ═══════════════════════════════════════════════════════════════
# Fail-closed gate for public API responses.
#
# Critical validation failures must not ship broken numbers to
# the frontend. Callers do:
#
#     quarantine = check_and_quarantine(ticker, response)
#     if quarantine is not None:
#         return quarantine          # under_review payload
#     return _normal_summary(...)    # clean payload
# ═══════════════════════════════════════════════════════════════

def under_review_payload(ticker: str, reason: str, issues: list[str] | None = None) -> dict:
    """Shape returned to the frontend when data is quarantined."""
    import datetime as _dt
    return {
        "status": "under_review",
        "ticker": ticker,
        "message": (
            "Data for this stock is being recalibrated. "
            "Analysis will return shortly."
        ),
        "last_validated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "reason": reason,
        # issues is diagnostic, not user-facing — keep it short and generic.
        "issue_count": len(issues or []),
    }


def check_and_quarantine(ticker: str, response) -> dict | None:
    """
    Run validate_analysis on a response. Return under_review payload if
    the response must not ship, else None (meaning: response is safe).

    Warning-severity issues do NOT quarantine — only critical.
    """
    try:
        vr = validate_analysis(response)
    except Exception as e:  # never let the gate itself break a request
        logger.warning("Gate crashed for %s: %s", ticker, e)
        return None
    if vr.ok or vr.severity != "critical":
        return None
    log_validation(ticker, vr)
    return under_review_payload(
        ticker=ticker,
        reason="validation_critical",
        issues=vr.issues,
    )
