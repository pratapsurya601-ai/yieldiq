"""
Formatting utilities for YieldIQ dashboard.
Handles number formatting, signal translation, and label prettification.
"""

def fmt(v, sym, d=2):
    """
    Format number with K/M/B/T suffix.
    
    Args:
        v: Number to format
        sym: Currency symbol (e.g., '$', '₹')
        d: Decimal places (default 2)
    
    Returns:
        Formatted string (e.g., '$1.5B', '₹234.56M')
    """
    a = abs(v)
    if a >= 1e12: return f"{sym}{v/1e12:,.2f}T"
    if a >= 1e9:  return f"{sym}{v/1e9:,.2f}B"
    if a >= 1e6:  return f"{sym}{v/1e6:,.2f}M"
    return f"{sym}{v:,.{d}f}"


def fmts(v, sym):
    """Simple number formatting with symbol."""
    return f"{sym}{v:,.2f}"


# Signal translation mapping
_SIG_HUMAN = {
    "Undervalued 🟢":    ("📊 Undervalued by model estimate",  "#185FA5", "#EFF6FF", "#BFDBFE"),
    "Near Fair Value 🟡":("📉 Slightly below model fair value", "#B45309", "#FFFBEB", "#FDE68A"),
    "Fairly Valued 🔵":  ("⚖️ Near model fair value",           "#475569", "#F8FAFC", "#E2E8F0"),
    "Overvalued 🔴":     ("📈 Overvalued by model estimate",    "#B45309", "#FFFBEB", "#FDE68A"),
    "⚠️ Data Limited":   ("🔍 Model data needs review",         "#B45309", "#FFFBEB", "#FDE68A"),
    "N/A ⬜":            ("⏳ Analysing…",                     "#4A5E7A", "#FFFFFF", "#F8FAFC"),
}


def sig_human(sig):
    """
    Return human-readable signal information.
    
    Args:
        sig: Signal string (e.g., "Undervalued 🟢")
    
    Returns:
        Tuple of (human_label, fg_color, bg_color, border_color)
    """
    return _SIG_HUMAN.get(sig, ("⏳ Analysing…", "#4A5E7A", "#FFFFFF", "#F8FAFC"))


def mos_insight(mos_pct: float, sig: str, company: str, suspicious: bool) -> str:
    """
    Generate one-line model output summary.
    No investment advice language - purely model estimates.
    
    Args:
        mos_pct: Margin of safety percentage
        sig: Signal string
        company: Company name
        suspicious: Whether financials show unusual patterns
    
    Returns:
        Insight string for display
    """
    if suspicious:
        return f"⚠️ {company}'s financials show unusual patterns — model estimates may be unreliable."
    if mos_pct >= 20:
        return f"📊 Our model estimates {company} is trading ~{mos_pct:.0f}% below its calculated fair value."
    elif mos_pct >= 5:
        return f"📊 Our model estimates {company} is trading ~{mos_pct:.0f}% below its calculated fair value."
    elif mos_pct >= -5:
        return f"⚖️ {company} is trading close to our model's estimated fair value."
    elif mos_pct >= -15:
        return f"📊 Our model estimates {company} is trading ~{abs(mos_pct):.0f}% above its calculated fair value."
    else:
        return f"📊 Our model estimates {company} is trading ~{abs(mos_pct):.0f}% above its calculated fair value."


def format_currency_regional(value: float, region: str = "IN", sym: str = "") -> str:
    """
    Format currency value with region-appropriate abbreviation.
    India: ₹1.2Cr, ₹45.3L, ₹12,345
    US/UK: $1.2B, $45.3M, $12,345
    """
    if not sym:
        sym = "₹" if region == "IN" else "$"

    _abs = abs(value)

    if region == "IN":
        if _abs >= 1e7:
            return f"{sym}{value / 1e7:.1f}Cr"
        elif _abs >= 1e5:
            return f"{sym}{value / 1e5:.1f}L"
        return f"{sym}{value:,.0f}"
    else:
        if _abs >= 1e9:
            return f"{sym}{value / 1e9:.1f}B"
        elif _abs >= 1e6:
            return f"{sym}{value / 1e6:.1f}M"
        return f"{sym}{value:,.0f}"


def format_market_cap(value: float, region: str = "IN", sym: str = "") -> str:
    """Format market cap with appropriate scale."""
    if not sym:
        sym = "₹" if region == "IN" else "$"

    if region == "IN":
        if value >= 1e7:
            return f"{sym}{value / 1e7:,.0f}Cr"
        elif value >= 1e5:
            return f"{sym}{value / 1e5:,.0f}L"
        return f"{sym}{value:,.0f}"
    else:
        if value >= 1e12:
            return f"{sym}{value / 1e12:.2f}T"
        elif value >= 1e9:
            return f"{sym}{value / 1e9:.1f}B"
        elif value >= 1e6:
            return f"{sym}{value / 1e6:.1f}M"
        return f"{sym}{value:,.0f}"


def get_region() -> str:
    """Get current region from config."""
    try:
        from config.countries import get_active_country
        return get_active_country().get("code", "IN")
    except Exception:
        return "IN"


def plain_kpi_label(label: str) -> str:
    """
    Translate finance jargon into plain English for KPI cards.
    
    Args:
        label: Technical label (e.g., "WACC", "Op Margin")
    
    Returns:
        Plain English label
    """
    _MAP = {
        "Margin of Safety":   "Discount to fair value",
        "WACC":               "Required return rate",
        "Op Margin":          "Profit per ₹100 revenue",
        "FCF Growth":         "Cash flow growth",
        "Revenue Growth":     "Revenue growth",
        "Confidence":         "Model reliability",
        "Intrinsic Value":    "Estimated fair value",
        "IV (DCF+PE Blend)":  "Estimated fair value",
        "Intrinsic Value (DCF)": "Estimated fair value",
        "Current Price":      "Current price",
    }
    return _MAP.get(label, label)
