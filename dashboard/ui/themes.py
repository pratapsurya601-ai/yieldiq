# dashboard/ui/themes.py
from __future__ import annotations

THEMES: dict[str, dict] = {

    # -- DARK JEWEL THEMES --

    "forest": {
        "name": "Forest", "emoji": "\U0001f33f", "dark": True,
        "desc": "Deep emerald \u00b7 Earthy & warm",
        "bg": "#0A2015", "bg2": "#0D2A1A", "bg3": "#102E1D",
        "bg4": "#163D26", "bg5": "#08180F",
        "border": "#1A4028", "border2": "#215033",
        "text": "#E8FCF2", "text2": "#7ABCA0", "text3": "#4A8A6A",
        "accent": "#22A860", "accent_dim": "#0D3D22",
        "positive": "#4DCC88", "positive_bg": "#0D3D22",
        "negative": "#FF7070", "negative_bg": "#3D0D0D",
        "warning": "#FFCC44", "warning_bg": "#3D3000",
        "neutral": "#7ABCA0", "neutral_bg": "#163D26",
        "bar_valuation": "#FF7070", "bar_quality": "#4DCC88",
        "bar_growth": "#60B4E0", "bar_sentiment": "#FFCC44",
        "chart_bg": "#0D2A1A", "chart_paper": "#0A2015",
        "chart_font": "#7ABCA0", "chart_grid": "rgba(255,255,255,0.05)",
        "chart_line": "#4DCC88", "chart_fill": "rgba(77,204,136,0.15)",
        "chart_bar_pos": "#4DCC88", "chart_bar_neg": "#FF7070",
        "chart_bar_neu": "#60B4E0",
        "chart_accent2": "#60B4E0", "chart_accent3": "#FFCC44",
        "chart_heatmap": "Greens",
        "btn_primary_bg": "#22A860", "btn_primary_fg": "#FFFFFF",
        "btn_secondary_bg": "#163D26", "btn_secondary_fg": "#7ABCA0",
        "sidebar_bg": "#08180F", "sidebar_border": "#1A4028",
        "sidebar_active": "#163D26", "sidebar_text": "#7ABCA0",
        "sidebar_accent": "#4DCC88",
    },

    "ocean": {
        "name": "Ocean", "emoji": "\U0001f30a", "dark": True,
        "desc": "Deep teal \u00b7 Rich & immersive",
        "bg": "#0A2A35", "bg2": "#0D3545", "bg3": "#103D50",
        "bg4": "#144860", "bg5": "#081E28",
        "border": "#1A4A5A", "border2": "#205870",
        "text": "#E8F8FC", "text2": "#7ABCCC", "text3": "#4A8A9A",
        "accent": "#0EA5C4", "accent_dim": "#0D3D50",
        "positive": "#4CAF80", "positive_bg": "#0D3D28",
        "negative": "#FF6B6B", "negative_bg": "#3D1010",
        "warning": "#FFBB44", "warning_bg": "#3D2D00",
        "neutral": "#7ABCCC", "neutral_bg": "#103D50",
        "bar_valuation": "#FF6B6B", "bar_quality": "#4CAF80",
        "bar_growth": "#4DD8E8", "bar_sentiment": "#FFBB44",
        "chart_bg": "#0D3545", "chart_paper": "#0A2A35",
        "chart_font": "#7ABCCC", "chart_grid": "rgba(255,255,255,0.05)",
        "chart_line": "#4DD8E8", "chart_fill": "rgba(77,216,232,0.15)",
        "chart_bar_pos": "#4CAF80", "chart_bar_neg": "#FF6B6B",
        "chart_bar_neu": "#4DD8E8",
        "chart_accent2": "#60C8E0", "chart_accent3": "#FFBB44",
        "chart_heatmap": "Teal",
        "btn_primary_bg": "#0EA5C4", "btn_primary_fg": "#FFFFFF",
        "btn_secondary_bg": "#103D50", "btn_secondary_fg": "#7ABCCC",
        "sidebar_bg": "#081E28", "sidebar_border": "#1A4A5A",
        "sidebar_active": "#103D50", "sidebar_text": "#7ABCCC",
        "sidebar_accent": "#4DD8E8",
    },

    # -- LIGHT THEMES --

    "aurora": {
        "name": "Aurora", "emoji": "\U0001f305", "dark": False,
        "desc": "Warm cream \u00b7 Soft & inviting",
        "bg": "#FFF8F0", "bg2": "#FFF3E8", "bg3": "#FAEEE0",
        "bg4": "#F5E6D4", "bg5": "#FAF0E8",
        "border": "#F0D5C0", "border2": "#E8C8A8",
        "text": "#3D1F10", "text2": "#8B6050", "text3": "#C4785A",
        "accent": "#C4785A", "accent_dim": "#FAE8E0",
        "positive": "#5A8C50", "positive_bg": "#EAF5E0",
        "negative": "#C44040", "negative_bg": "#FAEAEA",
        "warning": "#C49030", "warning_bg": "#FAF0D0",
        "neutral": "#8B7060", "neutral_bg": "#F5EDE0",
        "bar_valuation": "#C46060", "bar_quality": "#6B9E60",
        "bar_growth": "#7B9EC0", "bar_sentiment": "#C49030",
        "chart_bg": "#FFF3E8", "chart_paper": "#FFF8F0",
        "chart_font": "#8B6050", "chart_grid": "rgba(0,0,0,0.05)",
        "chart_line": "#C4785A", "chart_fill": "rgba(196,120,90,0.12)",
        "chart_bar_pos": "#6B9E60", "chart_bar_neg": "#C46060",
        "chart_bar_neu": "#7B9EC0",
        "chart_accent2": "#7B9EC0", "chart_accent3": "#C49030",
        "chart_heatmap": "Oranges",
        "btn_primary_bg": "#C4785A", "btn_primary_fg": "#FFFFFF",
        "btn_secondary_bg": "#F0DDD0", "btn_secondary_fg": "#8B6050",
        "sidebar_bg": "#FAF0E8", "sidebar_border": "#F0D5C0",
        "sidebar_active": "#F5E6D4", "sidebar_text": "#8B6050",
        "sidebar_accent": "#C4785A",
    },

    "sakura": {
        "name": "Sakura", "emoji": "\U0001f338", "dark": False,
        "desc": "Blush pink \u00b7 Feminine & elegant",
        "bg": "#FFF0F5", "bg2": "#FDE8EF", "bg3": "#FAE0EA",
        "bg4": "#F5D0E0", "bg5": "#FADDE8",
        "border": "#F0C4D4", "border2": "#E8B0C4",
        "text": "#2D0A18", "text2": "#8B4560", "text3": "#C45878",
        "accent": "#D4547A", "accent_dim": "#FAD8E4",
        "positive": "#5A9E6A", "positive_bg": "#E0F5E8",
        "negative": "#C44060", "negative_bg": "#FAE0EA",
        "warning": "#C49030", "warning_bg": "#FAF0D0",
        "neutral": "#8B6070", "neutral_bg": "#F5E8EE",
        "bar_valuation": "#E05878", "bar_quality": "#7BC47E",
        "bar_growth": "#A07CE0", "bar_sentiment": "#C4A040",
        "chart_bg": "#FDE8EF", "chart_paper": "#FFF0F5",
        "chart_font": "#8B4560", "chart_grid": "rgba(0,0,0,0.05)",
        "chart_line": "#D4547A", "chart_fill": "rgba(212,84,122,0.12)",
        "chart_bar_pos": "#7BC47E", "chart_bar_neg": "#E05878",
        "chart_bar_neu": "#A07CE0",
        "chart_accent2": "#A07CE0", "chart_accent3": "#C4A040",
        "chart_heatmap": "RdPu",
        "btn_primary_bg": "#D4547A", "btn_primary_fg": "#FFFFFF",
        "btn_secondary_bg": "#F5C8D8", "btn_secondary_fg": "#8B4560",
        "sidebar_bg": "#FADDE8", "sidebar_border": "#F0C4D4",
        "sidebar_active": "#F5D0E0", "sidebar_text": "#8B4560",
        "sidebar_accent": "#D4547A",
    },

    "violet": {
        "name": "Violet Mist", "emoji": "\U0001f49c", "dark": False,
        "desc": "Soft lavender \u00b7 Sophisticated",
        "bg": "#F5F0FF", "bg2": "#EDE8FF", "bg3": "#E4DCFF",
        "bg4": "#D8CEFF", "bg5": "#EAE0FF",
        "border": "#D4C8F0", "border2": "#C4B4E8",
        "text": "#1A0D38", "text2": "#5B3A8B", "text3": "#7B5AC4",
        "accent": "#8B5CF6", "accent_dim": "#EAE0FF",
        "positive": "#4A9E6A", "positive_bg": "#E0F5EA",
        "negative": "#B44080", "negative_bg": "#FAE0EE",
        "warning": "#A08030", "warning_bg": "#F5ECD0",
        "neutral": "#7060A0", "neutral_bg": "#EDE8FF",
        "bar_valuation": "#C060A0", "bar_quality": "#6BBE7C",
        "bar_growth": "#818CF8", "bar_sentiment": "#C0A840",
        "chart_bg": "#EDE8FF", "chart_paper": "#F5F0FF",
        "chart_font": "#5B3A8B", "chart_grid": "rgba(0,0,0,0.05)",
        "chart_line": "#8B5CF6", "chart_fill": "rgba(139,92,246,0.12)",
        "chart_bar_pos": "#6BBE7C", "chart_bar_neg": "#C060A0",
        "chart_bar_neu": "#818CF8",
        "chart_accent2": "#818CF8", "chart_accent3": "#C0A840",
        "chart_heatmap": "Purples",
        "btn_primary_bg": "#8B5CF6", "btn_primary_fg": "#FFFFFF",
        "btn_secondary_bg": "#DDD0F8", "btn_secondary_fg": "#7B5AC4",
        "sidebar_bg": "#EAE0FF", "sidebar_border": "#D4C8F0",
        "sidebar_active": "#E4DCFF", "sidebar_text": "#5B3A8B",
        "sidebar_accent": "#8B5CF6",
    },

    "slate": {
        "name": "Slate", "emoji": "\U0001faa8", "dark": False,
        "desc": "Cool grey \u00b7 Professional light",
        "bg": "#F8FAFC", "bg2": "#F1F5F9", "bg3": "#E8EEF4",
        "bg4": "#E2E8F0", "bg5": "#EDF2F7",
        "border": "#CBD5E1", "border2": "#B0BEC5",
        "text": "#0F172A", "text2": "#475569", "text3": "#64748B",
        "accent": "#1D4ED8", "accent_dim": "#EBF5FF",
        "positive": "#16A34A", "positive_bg": "#F0FDF4",
        "negative": "#DC2626", "negative_bg": "#FEF2F2",
        "warning": "#D97706", "warning_bg": "#FFFBEB",
        "neutral": "#475569", "neutral_bg": "#F1F5F9",
        "bar_valuation": "#DC2626", "bar_quality": "#16A34A",
        "bar_growth": "#1D4ED8", "bar_sentiment": "#D97706",
        "chart_bg": "#F1F5F9", "chart_paper": "#F8FAFC",
        "chart_font": "#475569", "chart_grid": "rgba(0,0,0,0.06)",
        "chart_line": "#1D4ED8", "chart_fill": "rgba(29,78,216,0.10)",
        "chart_bar_pos": "#16A34A", "chart_bar_neg": "#DC2626",
        "chart_bar_neu": "#1D4ED8",
        "chart_accent2": "#0891B2", "chart_accent3": "#D97706",
        "chart_heatmap": "Blues",
        "btn_primary_bg": "#1D4ED8", "btn_primary_fg": "#FFFFFF",
        "btn_secondary_bg": "#E2E8F0", "btn_secondary_fg": "#475569",
        "sidebar_bg": "#EDF2F7", "sidebar_border": "#CBD5E1",
        "sidebar_active": "#E2E8F0", "sidebar_text": "#475569",
        "sidebar_accent": "#1D4ED8",
    },
}

DEFAULT_THEME = "forest"
THEME_ORDER   = ["forest", "ocean", "aurora", "sakura", "violet", "slate"]


def get_theme(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def get_all_themes() -> list[dict]:
    return [{"key": k, **THEMES[k]} for k in THEME_ORDER]


def get_signal_style(mos_pct: float, theme_name: str) -> dict:
    t = get_theme(theme_name)
    if mos_pct >= 30:
        return {"label": "High Margin of Safety",
                "sub":   "Model: significantly undervalued",
                "color": t["positive"], "bg": t["positive_bg"]}
    elif mos_pct >= 10:
        return {"label": "Undervalued",
                "sub":   "Model estimate above current price",
                "color": t["positive"], "bg": t["positive_bg"]}
    elif mos_pct >= -5:
        return {"label": "Near Fair Value",
                "sub":   "Model estimate close to market price",
                "color": t["warning"],  "bg": t["warning_bg"]}
    elif mos_pct >= -20:
        return {"label": "Overvalued",
                "sub":   "Price above model fair value estimate",
                "color": t["negative"], "bg": t["negative_bg"]}
    else:
        return {"label": "Significantly Overvalued",
                "sub":   "Price well above model fair value",
                "color": t["negative"], "bg": t["negative_bg"]}
