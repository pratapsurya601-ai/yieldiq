"""
YieldIQ Composite Score calculation.
Pure scoring function - no Streamlit dependencies.
"""

def compute_yieldiq_score(
    mos_pct: float,
    piotroski: int,
    moat_grade: str,
    rev_growth: float,
    analyst_upside: float,
) -> dict:
    """
    Compute YieldIQ Composite Score (0-100).
    
    Scoring breakdown (quality-focused, ~70% quality / ~30% value):
    - Business Quality: 50 points (Piotroski F-Score 25 + Economic Moat 25)
    - Growth: 20 points (Revenue growth trajectory)
    - Valuation: 20 points (Margin of safety)
    - Sentiment: 10 points (Analyst consensus upside)

    Rationale: MoS reflects *price*, not business quality. Over-weighting it
    penalizes premium-priced compounders (e.g. Nestle, Asian Paints, Titan)
    whose fundamentals are excellent but whose market price leaves little
    margin of safety. Quality (ROE/ROCE proxied by Piotroski + durable moat)
    should dominate the composite.

    Model output for informational purposes only. Not investment advice.

    Args:
        mos_pct: Margin of safety percentage
        piotroski: Piotroski F-Score (0-9)
        moat_grade: Economic moat grade ("Wide", "Narrow", "None", or A-D)
        rev_growth: Revenue growth rate (%)
        analyst_upside: Analyst target upside (%)

    Returns:
        Dict with 'score' (0-100), 'grade' (A+ to D), and 'components' breakdown
    """
    # Valuation (20 pts) — reduced weight; MoS is a price signal, not quality
    #
    # CAP (2026-04-29, fix/bank-classifier): clamp mos_pct to [-50, +50]
    # before bucketing. Pre-cap, a misclassified bank (e.g. CAPITALSFB.NS
    # surfaced via yfinance with sector="Chemicals" pre-fix) ran the
    # FCF-DCF path and produced FV=999 vs price=257 → MoS=+289%, which
    # bucketed into the top val=20 slot and lifted YieldIQ to 89 / A+
    # despite the hex composite of ~5/10. The bank-classifier fix in
    # this PR removes the root cause for CAPITALSFB, but a hard cap
    # here is defence-in-depth: an extreme MoS reading is more likely
    # a model failure than a 3-5x mispricing of a real business, so
    # truncating to ±50% prevents any future classifier gap from
    # producing a contradictory headline grade.
    try:
        _mos_for_score = max(-50.0, min(50.0, float(mos_pct)))
    except (TypeError, ValueError):
        _mos_for_score = 0.0
    if _mos_for_score >= 40:    val_score = 20
    elif _mos_for_score >= 25:  val_score = 16
    elif _mos_for_score >= 10:  val_score = 12
    elif _mos_for_score >= 0:   val_score = 8
    elif _mos_for_score >= -15: val_score = 5
    elif _mos_for_score >= -30: val_score = 3
    else:                       val_score = 0

    # Business Quality (50 pts) — Piotroski (25) + Moat (25)
    pio_score = min(piotroski / 9 * 25, 25)
    # BUG FIX (2026-04-24): "Moderate" moat was not in the map, so every
    # Moderate-moat ticker (HDFCBANK, ICICIBANK, TCS, HCLTECH, MARUTI, HUL,
    # NESTLE, ASIANPAINT etc.) was scored as no-moat (0 pts instead of ~15).
    # This alone was dragging composite scores down 15-20 points across
    # most of the Nifty-30. Also added A+ / B+ / C+ grade variants to avoid
    # similar misses from the narrative-layer grade output.
    _moat_map = {
        # Numeric grades (from moat_service)
        "A+": 25, "A": 25, "B+": 22, "B": 18, "C+": 13, "C": 10, "D": 3,
        # Narrative grades (from hex_service / prism)
        "Wide": 25, "Narrow": 18, "Moderate": 15,
        # Absent-moat variants
        "None": 0, "none": 0, "N/A": 0, "n/a": 0, "": 0,
    }
    moat_pts   = _moat_map.get(str(moat_grade).strip(), 0)
    qual_score = pio_score + moat_pts

    # Growth (20 pts)
    # BUG FIX (2026-04-24): rev_growth arrives in DECIMAL form from
    # `enriched["revenue_growth"]` (e.g. 0.15 = 15%), but this formula
    # was calibrated for PERCENT (15 = 15%). Result: every growing
    # company got grw_score=5 (the "rev_growth >= 0" bucket) instead
    # of 10-20. Detect decimal form (|rev_growth| < 1.5) and convert
    # to percent. 1.5x is the threshold because decimal growth beyond
    # 150% is unrealistic for annual revenue — any value >= 1.5 is
    # almost certainly already in percent units.
    _rg = rev_growth
    try:
        if _rg is not None and -1.5 < float(_rg) < 1.5:
            _rg = float(_rg) * 100.0
    except (TypeError, ValueError):
        _rg = 0
    if _rg >= 20:    grw_score = 20
    elif _rg >= 10:  grw_score = 15
    elif _rg >= 5:   grw_score = 10
    elif _rg >= 0:   grw_score = 5
    else:            grw_score = 0

    # Sentiment (10 pts)
    # GUARD (2026-04-30): coerce analyst_upside to float defensively. If
    # upstream passes None (Finnhub target absent) or a string, the bare
    # comparisons below raise TypeError, which trips the fallback path in
    # backend/services/analysis/service.py and silently re-scores the
    # ticker without a moat-Moderate bucket. Treat unparseable as 0 (the
    # neutral "no signal" bucket → sent_score=4).
    try:
        _au = float(analyst_upside) if analyst_upside is not None else 0.0
    except (TypeError, ValueError):
        _au = 0.0
    if _au >= 20:    sent_score = 10
    elif _au >= 10:  sent_score = 7
    elif _au >= 0:   sent_score = 4
    else:            sent_score = 1

    total = max(0, min(100, int(val_score + qual_score + grw_score + sent_score)))

    # Letter grade assignment
    if total >= 85:   grade = "A+"
    elif total >= 75: grade = "A"
    elif total >= 65: grade = "B+"
    elif total >= 55: grade = "B"
    elif total >= 45: grade = "C+"
    elif total >= 35: grade = "C"
    else:             grade = "D"

    return {
        "score": total,
        "grade": grade,
        "components": {
            "Business Quality (50pts)": int(qual_score),
            "Growth (20pts)":           int(grw_score),
            "Valuation (20pts)":        int(val_score),
            "Sentiment (10pts)":        int(sent_score),
        },
    }
