# backend/validators/consistency.py
# ═══════════════════════════════════════════════════════════════
# Cross-field consistency rules. Dict-based, mirroring the rules
# in backend/services/validators.py::validate_analysis so the
# ingestion and canary paths apply the same logic.
#
# Returns list[str] — empty means all rules pass.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def check_consistency(r: dict) -> list[str]:
    """
    Cross-field rules on a stock record dict. Shape matches the
    stock-summary endpoint / AnalysisResponse fields.
    """
    errors: list[str] = []

    fv = _f(r.get("fair_value"))
    cmp_price = _f(r.get("current_market_price") or r.get("current_price"))
    mos = _f(r.get("margin_of_safety") or r.get("mos"))
    wacc = _f(r.get("wacc"))
    rf = _f(r.get("risk_free_rate"))
    moat = r.get("moat")
    roce = _f(r.get("roce"))
    roe = _f(r.get("roe"))
    pio = _f(r.get("piotroski_score") or r.get("piotroski"))
    de = _f(r.get("de_ratio") or r.get("debt_to_equity"))
    confidence = _f(r.get("confidence") or r.get("confidence_score"))
    fcf_growth = _f(r.get("fcf_growth_rate") or r.get("fcf_growth"))

    # FV / CMP ratio sanity — wider at the critical gate, tighter at the warn gate.
    if fv is not None and cmp_price is not None and cmp_price > 0:
        ratio = fv / cmp_price
        if ratio > 5.0 or ratio < 0.20:
            errors.append(
                f"FV/CMP ratio={ratio:.2f} implausible (FV={fv:g}, CMP={cmp_price:g})"
            )
        elif (ratio > 3.0 or ratio < 0.5) and confidence is not None and confidence > 70:
            errors.append(
                f"FV/CMP ratio={ratio:.2f} at {confidence:.0f}% confidence — review"
            )

    # MoS must reconcile with FV and CMP (MoS is percent, (fv-cmp)/cmp*100)
    if fv is not None and cmp_price is not None and cmp_price > 0 and mos is not None:
        expected_pct = (fv - cmp_price) / cmp_price * 100.0
        # 2 percentage-points slack for rounding + moat IV adjustments
        if abs(expected_pct - mos) > 2.0:
            errors.append(
                f"MoS={mos:.1f}% inconsistent with (FV-CMP)/CMP={expected_pct:.1f}%"
            )

    # WACC must exceed risk-free rate (India RFR ~6.5%, so wacc >= 0.04 floor)
    if wacc is not None:
        if wacc < 0.04:
            errors.append(f"WACC {wacc*100:.2f}% below risk-free-rate floor")
        if rf is not None and wacc < rf:
            errors.append(f"WACC {wacc:.4f} < risk-free-rate {rf:.4f}")

    # Moat vs ROCE — Wide moat without capital efficiency is a contradiction.
    # ROCE here is PERCENT (YieldIQ convention), so threshold is 12 not 0.12.
    if moat == "Wide" and roce is not None and roce < 12.0:
        errors.append(f"Wide moat claimed but ROCE={roce:.1f}% < 12%")

    # Moat vs ROE — same class of check, weaker signal.
    if moat == "Wide" and roe is not None and roe < 8.0:
        errors.append(f"Wide moat with ROE {roe:.1f}% — inconsistent")

    # Piotroski–debt contradiction
    if pio is not None and pio >= 7 and de is not None and de > 2.0:
        errors.append(f"High F-Score {pio:.0f}/9 with D/E {de:.2f} — review")

    # FCF growth assumption sanity
    if fcf_growth is not None and fcf_growth > 0.25:
        errors.append(
            f"FCF growth {fcf_growth*100:.1f}% sustained 10y — historically rare"
        )

    return errors
