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
    
    Scoring breakdown:
    - Valuation: 40 points (based on margin of safety)
    - Business Quality: 30 points (Piotroski F-Score + Economic Moat)
    - Growth: 20 points (Revenue growth trajectory)
    - Sentiment: 10 points (Analyst consensus upside)
    
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
    # Valuation (40 pts)
    if mos_pct >= 40:    val_score = 40
    elif mos_pct >= 25:  val_score = 32
    elif mos_pct >= 10:  val_score = 22
    elif mos_pct >= 0:   val_score = 14
    elif mos_pct >= -15: val_score = 7
    else:                val_score = 0

    # Business Quality (30 pts) — Piotroski + Moat
    pio_score = min(piotroski / 9 * 20, 20)
    _moat_map = {
        "A": 10, "B": 7, "C": 4, "D": 1,
        "Wide": 10, "Narrow": 7,
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
            "Valuation (40pts)":        int(val_score),
            "Business Quality (30pts)": int(qual_score),
            "Growth (20pts)":           int(grw_score),
            "Sentiment (10pts)":        int(sent_score),
        },
    }
