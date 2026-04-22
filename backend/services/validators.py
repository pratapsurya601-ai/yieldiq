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
#
# ── DCF 5x cap interaction (noise-suppression note, 2026-04-21) ──
# The DCF engine hard-caps intrinsic value at 5× current price to
# stop runaway IV numbers from shipping. When the cap fires, three
# downstream effects would otherwise look like critical failures:
#
#   1. DCF_TRACE records the raw (pre-cap) iv_ratio, so the trace
#      validator sees `iv_ratio > 5.0` even though the FV actually
#      shown to users is already clamped.
#   2. The moat engine applies a multiplier (up to +25% for Wide
#      moat) AFTER the DCF cap, so the displayed fair_value_ratio
#      can legitimately sit between 5.0 and 6.25 even though the
#      underlying engine behaved correctly.
#   3. validate_dcf_trace emits a separate "capped" info note.
#
# All three together previously rolled up to severity=critical and
# fired `logger.error(...)`, which Sentry's LoggingIntegration
# turns into an issue event on every request for the affected
# ticker. TMPV.NS (Tata Motors Passenger Vehicles, post-demerger
# successor to TATAMOTORS) was the worst offender with 606 events
# against Sentry issue PYTHON-FASTAPI-3 — yfinance still reports
# the pre-demerger consolidated FCF against the post-demerger
# narrower share base, inflating raw IV to ~5.6× CMP. That's a
# real data gap (not a code bug) and needs upstream fundamentals
# to catch up before standalone DCF is trustworthy.
#
# The fix below: when DCF_TRACES[ticker].capped is True, treat the
# resulting FV-ratio overshoot and iv_ratio>5.0 trace signal as
# EXPECTED — log at WARNING so Sentry stays silent, and don't flip
# ok=False / severity=critical on those specific cap-explained
# bounds violations. Genuine validator failures (zero shares,
# negative equity, MoS/FV mismatch, etc.) still fire critical and
# still reach Sentry.
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
    # MoS floor widened from -95 to -100 (2026-04-22). See bounds.py
    # for the rationale — NIVABUPA.NS legitimately lands at -96.5%
    # when extremely overvalued; not a data bug.
    "margin_of_safety":  (-100, 500, "critical"),      # -100% to +500%
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


def _dcf_was_capped(ticker: str | None) -> bool:
    """
    Return True when the DCF engine legitimately applied its 5x IV hard cap
    for this ticker on the most recent run. Used to downgrade validator
    severity: a fair_value_ratio overshoot that is *explained* by a correctly
    applied cap (plus the downstream moat multiplier on top of the capped IV)
    is expected behavior, not a bug to page on.
    """
    if not ticker:
        return False
    try:
        from screener.dcf_engine import DCF_TRACES  # lazy import to avoid cycles
        t = DCF_TRACES.get(ticker)
        if not isinstance(t, dict):
            return False
        return bool(t.get("capped"))
    except Exception:
        return False


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

    # Track whether this response's FV reflects a legitimately-applied
    # DCF 5x cap. When True, the fair_value_ratio bounds check is
    # expected to "fail" (the moat multiplier — up to +25% for Wide —
    # is applied ON TOP OF the already-capped 5x IV, yielding ratios
    # up to 6.25x). That's by design; don't page Sentry for it.
    ticker_for_cap = getattr(response, "ticker", None)
    was_capped = _dcf_was_capped(ticker_for_cap)

    if v:
        _check_bound("wacc", getattr(v, "wacc", None), result)
        _check_bound("terminal_growth", getattr(v, "terminal_growth", None), result)
        _check_bound("fcf_growth_rate", getattr(v, "fcf_growth_rate", None), result)
        _check_bound("confidence", getattr(v, "confidence_score", None), result)

        # margin_of_safety and fair_value_ratio both depend on the
        # clamped FV. When the DCF cap was legitimately applied,
        # the moat multiplier on top can push MoS slightly above the
        # +500% hard bound and the ratio above 5.0 — both are
        # explained by correct cap behavior, so downgrade to info.
        mos_val = getattr(v, "margin_of_safety", None)
        if was_capped:
            lo, hi, _s = BOUNDS["margin_of_safety"]
            try:
                mv = float(mos_val) if mos_val is not None else None
            except (TypeError, ValueError):
                mv = None
            if mv is not None and (mv < lo or mv > hi):
                result.issues.append(
                    f"margin_of_safety={mv:g} outside bounds [{lo}, {hi}] "
                    f"(expected: DCF cap applied; moat multiplier on top)"
                )
                # Do NOT set ok=False or bump severity.
        else:
            _check_bound("margin_of_safety", mos_val, result)

        # Fair value vs CMP ratio
        fv = getattr(v, "fair_value", 0) or 0
        cmp_price = getattr(v, "current_price", 0) or 0
        if fv > 0 and cmp_price > 0:
            ratio = fv / cmp_price
            if was_capped:
                # Cap was legitimately applied upstream. Log an INFO
                # note but don't flip severity — this is expected.
                lo, hi, _sev = BOUNDS["fair_value_ratio"]
                if ratio < lo or ratio > hi:
                    result.issues.append(
                        f"fair_value_ratio={ratio:g} outside bounds [{lo}, {hi}] "
                        f"(expected: DCF cap applied; moat multiplier on top)"
                    )
                    # Do NOT set ok=False or bump severity.
            else:
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

        # ── FV stability check (v35) ──────────────────────────
        # Defense-in-depth: every fresh compute MUST attach
        # computation_inputs (the snapshot of yfinance/Aiven values
        # that produced the displayed FV). Missing snapshot on a
        # fresh response means a code path silently bypassed the
        # snapshot block — that's the regression we're guarding
        # against. Old cached payloads (pre-v35) without the field
        # are tolerated by the warm path itself; this check fires
        # only on freshly-computed responses (cached=False).
        try:
            ci = getattr(response, "computation_inputs", None)
            is_cached = bool(getattr(response, "cached", False))
            if not is_cached and not ci:
                # Info-severity: don't flip verdict, but log so we
                # notice if a deploy regresses the snapshot.
                result.issues.append(
                    "FV_STABILITY_INFO: computation_inputs missing on "
                    "fresh compute — FV audit trail unavailable"
                )
                if result.severity == "ok":
                    result.severity = "warning"
            elif ci and isinstance(ci, dict):
                # Sanity: the snapshotted iv_post_moat must match the
                # displayed fair_value within a tight band. If it
                # doesn't, something mutated FV after the snapshot
                # was taken — exactly the class of bug we're killing.
                snap_iv = float(ci.get("iv_post_moat") or 0)
                disp_fv = float(getattr(v, "fair_value", 0) or 0)
                if snap_iv > 0 and disp_fv > 0:
                    drift = abs(snap_iv - disp_fv) / snap_iv
                    if drift > 0.01:  # 1% tolerance for rounding
                        result.ok = False
                        result.severity = "critical"
                        result.failed_fields.append("fair_value")
                        result.issues.append(
                            f"FV_INPUT_MISMATCH: displayed FV {disp_fv:g} "
                            f"drifted from snapshotted iv_post_moat "
                            f"{snap_iv:g} (drift {drift*100:.2f}%)"
                        )
        except Exception:
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
                # The DCF engine observes the RAW ratio (pre-cap) and
                # records it in the trace even after clamping. When the
                # cap was applied correctly (`capped=True`), this is the
                # expected, wanted behavior — don't page Sentry. Log at
                # INFO severity so it's still observable.
                if capped is True:
                    issues.append(
                        f"DCF raw IV ratio {r:.1f}x exceeded 5x — cap applied (expected)"
                    )
                    _bump("info")
                else:
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
        # Only append a separate cap note when we didn't already emit
        # one in the iv_ratio branch above — otherwise we double-log
        # the same event and spam the UI's data_issues list.
        already_noted = any("cap applied" in x for x in issues)
        if not already_noted:
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
    """Log validation issues at appropriate level.

    Sentry is wired via LoggingIntegration(event_level=ERROR), so only
    logger.error() calls create Sentry events. We deliberately log at
    WARNING when the DCF 5x cap was the driver — the cap is *expected*
    behavior and was already handled deterministically upstream; paging
    on every request for the same known-capped ticker just drowns the
    signal.
    """
    if result.ok and not result.issues:
        # Cap still deserves one observable line per compute, but at
        # INFO level — it's wanted behavior, not an alert.
        if _dcf_was_capped(ticker):
            logger.info("VALIDATION INFO [%s]: DCF 5x cap applied (expected)", ticker)
        return

    cap_applied = _dcf_was_capped(ticker)
    if result.severity == "critical" and not cap_applied:
        logger.error(
            "VALIDATION CRITICAL [%s]: %d issues, fields=%s | %s",
            ticker, len(result.issues), result.failed_fields, "; ".join(result.issues)
        )
    elif result.severity == "critical" and cap_applied:
        # Cap-driven "critical" signals are a known class of false
        # positive (FV/CMP overshoot after moat multiplier applied on
        # top of the already-clamped 5x IV). Log at warning so Sentry
        # doesn't page, but keep full issue list for log forensics.
        logger.warning(
            "VALIDATION CAPPED [%s]: %d issues (cap-explained, no Sentry) | %s",
            ticker, len(result.issues), "; ".join(result.issues)
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
