# dashboard/utils/verdict_colors.py
# ═══════════════════════════════════════════════════════════════
# Single source of truth for verdict color mapping.
# All verdict chips must use these functions — never hardcode colors.
#
# Rules:
#   Undervalued → BLUE (never green — green implies "go"/buy)
#   Overvalued  → AMBER (never red — red reserved for genuine danger)
#   Fairly valued → GRAY
#   Avoid (neg FCF, extreme debt) → RED (genuine danger)
#   Red flags → RED (genuine danger)
#   Price change ↑ → green, ↓ → red (standard market convention)
#   Score > 75 → blue, 50-75 → amber, < 50 → red
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

# ── Color palettes ────────────────────────────────────────────
UNDERVALUED = {"text": "#185FA5", "bg": "#EFF6FF", "accent": "#BFDBFE", "dark": "#1E40AF"}
OVERVALUED  = {"text": "#B45309", "bg": "#FFFBEB", "accent": "#FDE68A", "dark": "#92400E"}
FAIRLY_VALUED = {"text": "#475569", "bg": "#F8FAFC", "accent": "#E2E8F0", "dark": "#334155"}
AVOID       = {"text": "#DC2626", "bg": "#FEF2F2", "accent": "#FECACA", "dark": "#991B1B"}

SCORE_HIGH  = {"text": "#1D4ED8", "bg": "#EFF6FF"}   # > 75
SCORE_MID   = {"text": "#D97706", "bg": "#FFFBEB"}   # 50-75
SCORE_LOW   = {"text": "#DC2626", "bg": "#FEF2F2"}   # < 50

PRICE_UP    = {"text": "#059669", "bg": "#F0FDF4"}    # green (standard)
PRICE_DOWN  = {"text": "#DC2626", "bg": "#FEF2F2"}    # red (standard)


def verdict_palette(verdict: str) -> dict:
    """Return the color palette for a verdict string."""
    v = verdict.lower().replace(" ", "_").replace("-", "_")
    if v in ("undervalued", "strong_buy", "buy", "discount"):
        return UNDERVALUED
    elif v in ("overvalued", "premium", "sell"):
        return OVERVALUED
    elif v in ("fairly_valued", "fair", "hold", "near_fair_value"):
        return FAIRLY_VALUED
    elif v in ("avoid", "danger", "strong_sell"):
        return AVOID
    return FAIRLY_VALUED


def verdict_chip_html(verdict: str, size: str = "normal") -> str:
    """
    Returns HTML for a verdict chip with correct color.
    verdict: "undervalued" | "fairly_valued" | "overvalued" | "avoid"
    size: "normal" | "large" | "small"
    """
    p = verdict_palette(verdict)
    _label = verdict.replace("_", " ").title()

    _sizes = {
        "small": ("9px", "2px 8px"),
        "normal": ("11px", "3px 12px"),
        "large": ("14px", "6px 18px"),
    }
    _fs, _pad = _sizes.get(size, _sizes["normal"])

    return (
        f'<span style="display:inline-block;background:{p["bg"]};color:{p["text"]};'
        f'font-size:{_fs};font-weight:700;padding:{_pad};border-radius:8px;'
        f'border:1px solid {p["accent"]};">{_label}</span>'
    )


def score_color(score: int) -> str:
    """Returns hex color string for a given YieldIQ score."""
    if score >= 75:
        return SCORE_HIGH["text"]   # blue
    elif score >= 50:
        return SCORE_MID["text"]    # amber
    return SCORE_LOW["text"]        # red


def score_bg(score: int) -> str:
    """Returns background color for a given YieldIQ score."""
    if score >= 75:
        return SCORE_HIGH["bg"]
    elif score >= 50:
        return SCORE_MID["bg"]
    return SCORE_LOW["bg"]


def mos_color(mos_pct: float) -> str:
    """Returns hex color for margin of safety percentage."""
    if mos_pct > 10:
        return UNDERVALUED["text"]   # blue — undervalued
    elif mos_pct > -10:
        return FAIRLY_VALUED["text"]  # gray — near fair value
    elif mos_pct > -30:
        return OVERVALUED["text"]    # amber — overvalued
    return AVOID["text"]             # red — significantly overvalued


def mos_bg(mos_pct: float) -> str:
    """Returns background color for margin of safety."""
    if mos_pct > 10:
        return UNDERVALUED["bg"]
    elif mos_pct > -10:
        return FAIRLY_VALUED["bg"]
    elif mos_pct > -30:
        return OVERVALUED["bg"]
    return AVOID["bg"]


def signal_color(signal: str) -> str:
    """Map signal labels like 'Undervalued', 'Overvalued' to correct hex."""
    return verdict_palette(signal)["text"]


def signal_bg(signal: str) -> str:
    """Map signal labels to background color."""
    return verdict_palette(signal)["bg"]
