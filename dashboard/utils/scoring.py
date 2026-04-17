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
    if mos_pct >= 40:    val_score = 20
    elif mos_pct >= 25:  val_score = 16
    elif mos_pct >= 10:  val_score = 12
    elif mos_pct >= 0:   val_score = 8
    elif mos_pct >= -15: val_score = 5
    elif mos_pct >= -30: val_score = 3
    else:                val_score = 0

    # Business Quality (50 pts) — Piotroski (25) + Moat (25)
    pio_score = min(piotroski / 9 * 25, 25)
    _moat_map = {
        "A": 25, "B": 18, "C": 10, "D": 3,
        "Wide": 25, "Narrow": 18,
        "None": 0, "none": 0, "N/A": 0, "": 0,
    }
    moat_pts   = _moat_map.get(str(moat_grade).strip(), 0)
    qual_score = pio_score + moat_pts

    # Growth (20 pts)
    if rev_growth >= 20:    grw_score = 20
    elif rev_growth >= 10:  grw_score = 15
    elif rev_growth >= 5:   grw_score = 10
    elif rev_growth >= 0:   grw_score = 5
    else:                   grw_score = 0

    # Sentiment (10 pts)
    if analyst_upside >= 20:    sent_score = 10
    elif analyst_upside >= 10:  sent_score = 7
    elif analyst_upside >= 0:   sent_score = 4
    else:                       sent_score = 1

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
