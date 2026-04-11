"""dashboard/ui/styles.py
All CSS and JS injections. Call inject_all() once at app startup.
"""
from __future__ import annotations
import streamlit as st



def inject_fonts() -> None:
    st.html("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@300;400;500;600;700&family=Barlow+Condensed:wght@500;600;700;800&display=swap" rel="stylesheet">
""")


def inject_main_css() -> None:
    st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════════════
   YIELDIQ DASHBOARD — PROFESSIONAL LIGHT THEME
   Fonts: Inter (UI) + IBM Plex Mono (numbers)
   Colors: Deep navy sidebar + clean white cards + blue accents
   ═══════════════════════════════════════════════════════════════ */

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@300;400;500;600;700&family=Barlow+Condensed:wght@500;600;700;800&display=swap');

/* ── DESIGN TOKENS ── */
:root {
  /* Core palette — matches your screenshot */
  --bg-page:      #EEF2F8;
  --bg-card:      #FFFFFF;
  --bg-card2:     #F7F9FC;
  --bg-sidebar:   #1A2540;
  --bg-sidebar2:  #0F1929;
  --bg-header:    linear-gradient(135deg, #1D3461 0%, #1E4D8C 100%);

  /* Accent blues */
  --blue:         #1D4ED8;
  --blue-mid:     #2563EB;
  --blue-lt:      #EFF6FF;
  --blue-glow:    rgba(29,78,216,0.12);
  --blue-border:  rgba(29,78,216,0.20);

  /* Signal colors */
  --green:        #059669;
  --green-lt:     #ECFDF5;
  --green-border: rgba(5,150,105,0.20);
  --red:          #DC2626;
  --red-lt:       #FEF2F2;
  --red-border:   rgba(220,38,38,0.20);
  --amber:        #D97706;
  --amber-lt:     #FFFBEB;
  --amber-border: rgba(217,119,6,0.20);

  /* Text */
  --text:         #0F172A;
  --text-sec:     #475569;
  --text-muted:   #94A3B8;
  --text-sidebar: #94A3B8;
  --text-sidebar2:#CBD5E1;

  /* Borders & shadows */
  --rule:         #E2E8F0;
  --rule2:        #CBD5E1;
  --shadow-sm:    0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04);
  --shadow-md:    0 4px 16px rgba(15,23,42,0.08), 0 2px 4px rgba(15,23,42,0.04);
  --shadow-lg:    0 10px 40px rgba(15,23,42,0.10), 0 4px 8px rgba(15,23,42,0.05);
  --shadow-blue:  0 4px 20px rgba(29,78,216,0.15);

  /* Typography — Bloomberg-accurate pairing
     UI:      Inter (matches Neue Haas Grotesk's Swiss grotesque tradition)
     Data:    IBM Plex Mono (designed for financial data display, tabular figures)
     Display: Barlow Condensed (heavy condensed grotesque = Druk feel) */
  --font-ui:      'Inter', system-ui, -apple-system, sans-serif;
  --font-mono:    'IBM Plex Mono', 'Courier New', monospace;
  --font-display: 'Barlow Condensed', 'Inter', sans-serif;

  /* Radius */
  --r-sm:   6px;
  --r:      10px;
  --r-lg:   14px;
  --r-xl:   20px;
}

/* ── ANIMATIONS ── */
@keyframes fadeSlideUp   { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
@keyframes pulseGreen    { 0%,100% { box-shadow:0 0 0 0 rgba(5,150,105,0.3); } 70% { box-shadow:0 0 0 6px rgba(5,150,105,0); } }
@keyframes pulseBlue     { 0%,100% { box-shadow:0 0 0 0 rgba(29,78,216,0.25); } 70% { box-shadow:0 0 0 6px rgba(29,78,216,0); } }
@keyframes shimmer       { 0%,100% { opacity:1; } 50% { opacity:0.7; } }
@keyframes barGrow       { from { transform:scaleX(0); } to { transform:scaleX(1); } }

/* ── BASE ── */
*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] {
  font-family: var(--font-ui) !important;
  background: var(--bg-page) !important;
  color: var(--text) !important;
  font-size: 13px !important;
}
.stApp { background: var(--bg-page) !important; }
.main .block-container {
  padding: 0 2.5rem 3rem 2.5rem !important;
  max-width: 1560px !important;
}

/* ── SIDEBAR ── */
section[data-testid="stSidebar"] {
  background: var(--bg-sidebar) !important;
  border-right: none !important;
  box-shadow: 4px 0 32px rgba(0,0,0,0.25) !important;
}
section[data-testid="stSidebar"] .block-container {
  padding: 1.5rem 1.2rem !important;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div {
  color: var(--text-sidebar) !important;
  font-size: 12px !important;
  font-family: var(--font-ui) !important;
}
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stNumberInput input {
  background: rgba(255,255,255,0.07) !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  color: #E2E8F0 !important;
  border-radius: var(--r-sm) !important;
  font-family: var(--font-mono) !important;
  font-size: 13px !important;
  transition: all 0.2s !important;
}
section[data-testid="stSidebar"] .stTextInput input:focus {
  border-color: rgba(59,130,246,0.6) !important;
  background: rgba(255,255,255,0.10) !important;
  box-shadow: 0 0 0 3px rgba(59,130,246,0.15) !important;
}
section[data-testid="stSidebar"] .stSlider label,
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stTextInput label,
section[data-testid="stSidebar"] .stCheckbox label {
  color: rgba(148,163,184,0.8) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.10em !important;
  font-family: var(--font-mono) !important;
}
section[data-testid="stSidebar"] .stSlider [data-baseweb="slider"] > div:nth-child(3) {
  background: #3B82F6 !important;
}
section[data-testid="stSidebar"] .stSlider [data-testid="stThumbValue"] {
  background: #3B82F6 !important;
  color: #FFF !important;
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
}
/* Sidebar nav button styles are handled via st.markdown() above page config
   to ensure they apply to the parent DOM, not the sandboxed st.html() iframe. */
section[data-testid="stSidebar"] hr {
  border: none !important;
  border-top: 1px solid rgba(255,255,255,0.08) !important;
  margin: 1rem 0 !important;
}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] {
  background: transparent !important;
  border-bottom: 2px solid var(--rule) !important;
  gap: 0 !important;
  padding: 0 !important;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  color: var(--text-muted) !important;
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: 0.10em !important;
  text-transform: uppercase !important;
  padding: 14px 22px !important;
  transition: all 0.2s !important;
  border-radius: 0 !important;
  margin-bottom: -2px !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--text-sec) !important;
  background: var(--blue-lt) !important;
}
.stTabs [aria-selected="true"] {
  color: var(--blue) !important;
  border-bottom-color: var(--blue) !important;
  background: transparent !important;
}
.stTabs [data-baseweb="tab-panel"] {
  padding: 2rem 0 0 !important;
}

/* ── METRICS ── */
[data-testid="stMetric"] {
  background: var(--bg-card) !important;
  border: 1px solid var(--rule) !important;
  border-radius: var(--r) !important;
  padding: 16px 18px !important;
  box-shadow: var(--shadow-sm) !important;
  transition: all 0.2s !important;
}
[data-testid="stMetric"]:hover {
  border-color: var(--rule2) !important;
  box-shadow: var(--shadow-md) !important;
  transform: translateY(-1px) !important;
}
[data-testid="stMetricLabel"] p {
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  color: var(--text-muted) !important;
}
[data-testid="stMetricValue"] {
  font-family: var(--font-mono) !important;
  font-size: 24px !important;
  font-weight: 600 !important;
  color: var(--text) !important;
  letter-spacing: -0.5px !important;
}
[data-testid="stMetricDelta"] {
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
  font-weight: 500 !important;
}

/* ── BUTTONS ── */
.stButton > button {
  background: var(--bg-card) !important;
  color: var(--text-sec) !important;
  border: 1px solid var(--rule2) !important;
  border-radius: var(--r-sm) !important;
  font-family: var(--font-ui) !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  transition: all 0.2s !important;
  box-shadow: var(--shadow-sm) !important;
}
.stButton > button:hover {
  border-color: var(--blue) !important;
  color: var(--blue) !important;
  box-shadow: 0 0 0 3px var(--blue-glow) !important;
  transform: translateY(-1px) !important;
}



/* ── DATAFRAMES ── */
[data-testid="stDataFrame"] {
  border-radius: var(--r) !important;
  overflow: hidden !important;
  box-shadow: var(--shadow-sm) !important;
  border: 1px solid var(--rule) !important;
}
[data-testid="stDataFrame"] thead th {
  background: var(--bg-card2) !important;
  color: var(--text-muted) !important;
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: 0.10em !important;
  text-transform: uppercase !important;
  border-bottom: 1px solid var(--rule) !important;
  padding: 10px 14px !important;
}
[data-testid="stDataFrame"] tbody td {
  background: var(--bg-card) !important;
  color: var(--text-sec) !important;
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
  border-bottom: 1px solid var(--bg-card2) !important;
  padding: 10px 14px !important;
}
[data-testid="stDataFrame"] tbody tr:hover td {
  background: var(--blue-lt) !important;
  color: var(--text) !important;
}

/* ── CAPTIONS ── */
[data-testid="stCaptionContainer"] p,
.stMarkdown small {
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
  color: var(--text-muted) !important;
  letter-spacing: 0.03em !important;
}

/* ── SCROLLBAR ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg-page); }
::-webkit-scrollbar-thumb { background: var(--rule2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ── HIDE STREAMLIT CHROME ── */
#MainMenu { visibility: hidden; }
footer { display: none; }
.stDeployButton { display: none; }

/* ── AGGRESSIVE FONT OVERRIDE ── */
/* Target every possible Streamlit text element */
html, body,
.stApp, .stApp *,
[class*="st-"], 
p, div, span, label, input, button, select, textarea,
h1, h2, h3, h4, h5, h6 {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}

/* Numbers & monospace specifically */
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"],
[data-testid="stDataFrame"] td,
[data-testid="stDataFrame"] th,
code, pre, .stCodeBlock {
  font-family: 'IBM Plex Mono', 'Fira Code', 'Cascadia Code', 
               'Courier New', monospace !important;
}

/* ── PAGE BACKGROUND ── */
.stApp {
  background: #EEF2F8 !important;
}
.main > div {
  background: #EEF2F8 !important;
}

/* ── METRIC CARDS — BIG VISUAL UPGRADE ── */
[data-testid="stMetric"] {
  background: #FFFFFF !important;
  border: 1px solid #E2E8F0 !important;
  border-radius: 12px !important;
  padding: 18px 20px !important;
  box-shadow: 0 1px 3px rgba(15,23,42,0.07), 0 1px 2px rgba(15,23,42,0.04) !important;
  transition: box-shadow 0.2s, transform 0.2s !important;
}
[data-testid="stMetric"]:hover {
  box-shadow: 0 4px 16px rgba(15,23,42,0.10) !important;
  transform: translateY(-1px) !important;
}
[data-testid="stMetricLabel"] > div > p {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  color: #94A3B8 !important;
}
[data-testid="stMetricValue"] > div {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 24px !important;
  font-weight: 600 !important;
  letter-spacing: -0.5px !important;
  color: #0F172A !important;
}
[data-testid="stMetricDelta"] svg + div {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 12px !important;
  font-weight: 500 !important;
}

/* ── TAB UPGRADE ── */
.stTabs [data-baseweb="tab-list"] {
  gap: 0 !important;
  padding: 0 !important;
  background: transparent !important;
  border-bottom: 2px solid #E2E8F0 !important;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  border-bottom: 2px solid transparent !important;
  padding: 12px 22px !important;
  margin-bottom: -2px !important;
  border-radius: 0 !important;
  color: #94A3B8 !important;
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: 0.10em !important;
  text-transform: uppercase !important;
  transition: all 0.2s !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: #475569 !important;
  background: rgba(29,78,216,0.04) !important;
}
.stTabs [aria-selected="true"] {
  color: #1D4ED8 !important;
  border-bottom-color: #1D4ED8 !important;
}

/* ── BUTTON UPGRADE ── */
.stButton > button {
  font-family: 'Inter', sans-serif !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  letter-spacing: 0.01em !important;
  border-radius: 8px !important;
  transition: all 0.2s !important;
}

/* ── SIDEBAR TEXT OVERRIDE ── */
section[data-testid="stSidebar"] * {
  font-family: 'Inter', sans-serif !important;
}
section[data-testid="stSidebar"] [data-testid="stMetricValue"] > div,
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] code {
  font-family: 'IBM Plex Mono', monospace !important;
}

/* ── DATAFRAME UPGRADE ── */
[data-testid="stDataFrame"] {
  border: 1px solid #E2E8F0 !important;
  border-radius: 10px !important;
  overflow: hidden !important;
  box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
}
[data-testid="stDataFrame"] th {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  background: #F7F9FC !important;
  color: #94A3B8 !important;
  padding: 10px 14px !important;
  border-bottom: 1px solid #E2E8F0 !important;
}
[data-testid="stDataFrame"] td {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 12px !important;
  padding: 9px 14px !important;
  border-bottom: 1px solid #F8FAFC !important;
}
[data-testid="stDataFrame"] tr:hover td {
  background: #EFF6FF !important;
}



/* ── INPUT UPGRADE ── */
.stTextInput input, .stNumberInput input {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  letter-spacing: 0.02em !important;
}

/* ── CAPTION UPGRADE ── */
[data-testid="stCaptionContainer"] p {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 12px !important;
  letter-spacing: 0.04em !important;
  color: #94A3B8 !important;
}

/* ── SCROLLBAR ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #EEF2F8; }
::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #94A3B8; }



/* ══ EXPANDER STYLING v5 ══════════════════════════════════════
   Clean expander design. Hides native icons/SVGs but preserves
   ALL label text (p, span, or bare text nodes).
   ══════════════════════════════════════════════════════════════ */

/* Summary row layout */
[data-testid="stExpander"] summary,
details > summary {
  display:        flex         !important;
  align-items:    center       !important;
  gap:            10px         !important;
  list-style:     none         !important;
  cursor:         pointer      !important;
  padding:        11px 16px    !important;
  background:     #FAFBFC      !important;
  border-bottom:  1px solid #E2E8F0 !important;
  color:          #334155      !important;
  font-size:      13px         !important;
  font-weight:    500          !important;
}
/* Kill native disclosure triangle */
[data-testid="stExpander"] summary::-webkit-details-marker,
details > summary::-webkit-details-marker { display: none !important; }

/* Hide SVGs inside summary (Streamlit's expand/collapse icons) */
[data-testid="stExpander"] summary svg,
details > summary svg {
  display:  none !important;
  width:    0    !important;
  height:   0    !important;
}

/* ══ ICON TEXT FIX — CSS-only, bulletproof ══════════════════
   Streamlit renders Material icon names (keyboard_arrow_right,
   _expand_more, etc.) inside <span data-testid="stIconMaterial">.
   Hide these spans entirely via CSS — no JS needed. */
[data-testid="stIconMaterial"] {
  font-size:      0           !important;
  width:          0           !important;
  height:         0           !important;
  overflow:       hidden      !important;
  position:       absolute    !important;
  pointer-events: none        !important;
}

/* Ensure label text is visible — both p and span */
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span:not(:empty),
details > summary p,
details > summary span:not(:empty) {
  color:       #334155 !important;
  font-size:   13px    !important;
  font-weight: 500     !important;
  visibility:  visible !important;
  opacity:     1       !important;
  margin:      0       !important;
}

/* Sidebar expander labels — light text on dark bg */
section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
section[data-testid="stSidebar"] details > summary {
  background:  rgba(255,255,255,0.04) !important;
  border-bottom: 1px solid rgba(255,255,255,0.08) !important;
  color:       #CBD5E1 !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
section[data-testid="stSidebar"] [data-testid="stExpander"] summary span,
section[data-testid="stSidebar"] details > summary p,
section[data-testid="stSidebar"] details > summary span {
  color:       #CBD5E1 !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
section[data-testid="stSidebar"] details > summary:hover {
  background:  rgba(255,255,255,0.08) !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover p,
section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover span {
  color: #38BDF8 !important;
}

/* Custom CSS chevron */
[data-testid="stExpander"] summary::before,
details > summary::before {
  content:       ""               !important;
  display:       inline-block     !important;
  flex-shrink:   0                !important;
  width:         6px              !important;
  height:        6px              !important;
  border-right:  2px solid #94A3B8 !important;
  border-bottom: 2px solid #94A3B8 !important;
  transform:     rotate(-45deg)   !important;
  transition:    transform 0.2s ease !important;
  margin-right:  2px              !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary::before,
section[data-testid="stSidebar"] details > summary::before {
  border-color: #64748B !important;
}
details[open] > summary::before,
[data-testid="stExpander"][open] summary::before {
  transform: rotate(45deg) !important;
}
[data-testid="stExpander"] summary:hover,
details > summary:hover { background: #EFF6FF !important; }
[data-testid="stExpander"] summary:hover::before {
  border-color: #1D4ED8 !important;
}
[data-testid="stExpander"] summary:hover p,
[data-testid="stExpander"] summary:hover span,
details > summary:hover p,
details > summary:hover span { color: #1D4ED8 !important; }
/* ══ END EXPANDER STYLING ══ */

/* ══════════════════════════════════════════════════════════════
   INNER SUB-TABS — Make Summary/Valuation/Quality/Signals
   visually prominent, not like plain Streamlit tabs
   ══════════════════════════════════════════════════════════════ */

/* Target only the second level of tabs (inner sub-tabs)
   by using the parent container. The inner tabs are rendered
   inside the outer tab panel div. */

/* Make ALL tab lists look great */
[data-baseweb="tab-list"] {
  background:    #FFFFFF        !important;
  border-bottom: 2px solid #E2E8F0 !important;
  padding:       0              !important;
  gap:           0              !important;
  box-shadow:    0 1px 4px rgba(15,23,42,0.06) !important;
}
[data-baseweb="tab"] {
  background:     transparent   !important;
  border:         none          !important;
  border-bottom:  2px solid transparent !important;
  margin-bottom:  -2px          !important;
  color:          #94A3B8       !important;
  font-family:    'IBM Plex Mono', monospace !important;
  font-size:      11px          !important;
  font-weight:    700           !important;
  letter-spacing: 0.10em        !important;
  text-transform: uppercase     !important;
  padding:        13px 22px     !important;
  transition:     all 0.15s     !important;
  border-radius:  0             !important;
}
[data-baseweb="tab"]:hover {
  color:      #475569   !important;
  background: #EFF6FF   !important;
}
[aria-selected="true"] {
  color:              #1D4ED8   !important;
  border-bottom-color:#1D4ED8   !important;
  background:         transparent !important;
}
[data-baseweb="tab-panel"] {
  padding: 1.2rem 0 0 !important;
}
/* ══════════════════════════════════════════════════════════════
   MOBILE RESPONSIVE v2 — Complete overhaul
   Based on Apple HIG + Material Design touch guidelines
   ══════════════════════════════════════════════════════════════ */

/* ── ≤ 768px: Phone layout ──────────────────────────────────── */
@media (max-width: 768px) {

  /* Reduce container padding */
  .main .block-container {
    padding: 0.75rem 0.75rem 2rem !important;
    max-width: 100% !important;
  }

  /* Stack ALL columns vertically */
  [data-testid="stHorizontalBlock"] {
    flex-direction: column !important;
    gap: 6px !important;
    flex-wrap: nowrap !important;
  }
  [data-testid="stHorizontalBlock"] > div,
  [data-testid="column"] {
    width: 100% !important;
    min-width: 100% !important;
    flex: 1 1 100% !important;
  }

  /* KPI cards: 2 per row */
  [data-testid="stMetric"] {
    min-width: calc(50% - 6px) !important;
    padding: 10px 12px !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 20px !important;
  }
  [data-testid="stMetricLabel"] {
    font-size: 11px !important;
  }
  [data-testid="stMetricDelta"] {
    font-size: 11px !important;
  }

  /* Sidebar — hidden by default on mobile, slides in on tap */
  [data-testid="stSidebar"] {
    width: 80vw !important;
    max-width: 320px !important;
    min-width: unset !important;
    transform: translateX(-100%) !important;
    transition: transform 0.25s ease !important;
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    height: 100dvh !important;
    z-index: 999 !important;
    overflow-y: auto !important;
    box-shadow: 4px 0 24px rgba(0,0,0,0.4) !important;
  }
  /* When sidebar is open (Streamlit toggles aria-expanded) */
  [data-testid="stSidebar"][aria-expanded="true"] {
    transform: translateX(0) !important;
  }
  /* Collapse button always visible on mobile */
  [data-testid="stSidebarCollapsedControl"] {
    display: flex !important;
    position: fixed !important;
    top: 12px !important;
    left: 12px !important;
    z-index: 1000 !important;
    background: #1D4ED8 !important;
    border-radius: 8px !important;
    padding: 6px 10px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
  }
  [data-testid="stSidebarNav"] {
    display: none !important;
  }
  /* Main content: full width, add top padding for the menu button */
  .main {
    margin-left: 0 !important;
    padding-top: 52px !important;
  }

  /* Tabs: horizontal scroll */
  .stTabs [data-baseweb="tab-list"],
  [data-baseweb="tab-list"] {
    overflow-x: auto !important;
    flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch !important;
    scrollbar-width: none !important;
    gap: 0 !important;
  }
  .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none !important; }
  [data-baseweb="tab"] {
    padding: 12px 14px !important;
    font-size: 10px !important;
    white-space: nowrap !important;
    flex-shrink: 0 !important;
    min-height: 44px !important;
  }

  /* All buttons: 44px min height (Apple HIG) */
  [data-testid="baseButton-primary"],
  [data-testid="baseButton-secondary"],
  button[kind="primary"],
  button[kind="secondary"],
  .stButton > button {
    min-height: 44px !important;
    font-size: 13px !important;
    width: 100% !important;
    padding: 10px 16px !important;
  }

  /* Inputs: 44px min height + 16px font (prevents iOS zoom) */
  .stTextInput input,
  .stNumberInput input,
  .stSelectbox select,
  input[type="text"],
  input[type="number"] {
    font-size: 16px !important;
    min-height: 44px !important;
    padding: 10px 14px !important;
  }

  /* Selectbox */
  [data-baseweb="select"] {
    min-width: 100% !important;
  }
  [data-baseweb="select"] > div {
    min-height: 44px !important;
  }

  /* Sliders: constrained width + larger touch target */
  [data-testid="stSlider"] {
    padding: 8px 0 16px !important;
    max-width: 100% !important;
    overflow: hidden !important;
    box-sizing: border-box !important;
  }
  [data-testid="stSlider"] > div {
    max-width: 100% !important;
    overflow: hidden !important;
  }
  [data-testid="stSlider"] [data-baseweb="slider"] {
    max-width: 100% !important;
    padding: 0 4px !important;
  }
  /* Thumb: large enough to tap */
  [data-testid="stSlider"] [role="slider"] {
    width: 28px !important;
    height: 28px !important;
  }

  /* Expanders */
  details > summary,
  [data-testid="stExpander"] summary {
    min-height: 44px !important;
    padding: 12px 16px !important;
  }

  /* Plotly charts */
  .js-plotly-plot,
  .plotly,
  [data-testid="stPlotlyChart"] {
    max-width: 100% !important;
    height: auto !important;
    min-height: 200px !important;
    overflow: hidden !important;
  }

  /* DataFrames: horizontal scroll */
  [data-testid="stDataFrame"],
  [data-testid="stTable"] {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch !important;
    font-size: 11px !important;
  }

  /* iframes (TradingView chart) */
  iframe {
    max-width: 100% !important;
    width: 100% !important;
  }

  /* Hero section */
  .yiq-hero {
    padding: 28px 20px !important;
    flex-direction: column !important;
  }

  /* Scale down font sizes 20% */
  .stMarkdown p, .stMarkdown li {
    font-size: 13px !important;
    line-height: 1.6 !important;
  }

  /* Hide non-essential table columns */
  .hide-mobile { display: none !important; }

  /* st.html() card layouts */
  div[style*="display:grid"][style*="grid-template-columns"] {
    grid-template-columns: 1fr !important;
  }
  div[style*="display:flex"][style*="justify-content:space-between"] {
    flex-direction: column !important;
    gap: 10px !important;
  }

  /* Hero headline */
  div[style*="font-size:32px"],
  div[style*="font-size: 32px"] {
    font-size: 26px !important;
  }
  div[style*="font-size:40px"],
  div[style*="font-size: 40px"] {
    font-size: 28px !important;
  }
}

/* ── ≤ 480px: Small phone layout ────────────────────────────── */
@media (max-width: 480px) {

  /* Tabs: smaller labels */
  [data-baseweb="tab"] {
    padding: 10px 10px !important;
    font-size: 9px !important;
    letter-spacing: 0.04em !important;
  }

  /* Table cells: smaller font */
  [data-testid="stDataFrame"] td,
  [data-testid="stDataFrame"] th,
  [data-testid="stTable"] td,
  [data-testid="stTable"] th {
    font-size: 11px !important;
    padding: 4px 6px !important;
  }

  /* KPI cards: 1 per row on very small screens */
  [data-testid="stMetric"] {
    min-width: 100% !important;
  }

  /* Reduce container padding further */
  .main .block-container {
    padding: 0.5rem 0.5rem 2rem !important;
  }

  /* Progress bar */
  [data-testid="stProgressBar"] {
    height: 6px !important;
  }
}

/* ── Tablet: 769-1024px ──────────────────────────────────────── */
@media (min-width: 769px) and (max-width: 1024px) {
  .main .block-container {
    padding: 1rem 1.5rem !important;
    max-width: 100% !important;
  }
  [data-baseweb="tab"] {
    padding: 11px 14px !important;
    font-size: 11px !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 22px !important;
  }
}

</style>
""", unsafe_allow_html=True)


def inject_typography_css() -> None:
    st.markdown("""
<style>
/* ── TYPOGRAPHY SCALE ────────────────────────────────────────
   Page Title:      24px / 700 / 1.25  — app-level headings
   Section Header:  15px / 600 / 1.4   — tab & card section labels
   Card Title:      13px / 600 / 1.4   — inside card headers
   Body:            13px / 400 / 1.65  — all descriptive text
   Secondary:       12px / 400 / 1.55  — helper text, captions
   Label:           11px / 500 / 1.3   — ALL-CAPS metric labels
   Numbers/Prices:  IBM Plex Mono, sizes defined per context
   ──────────────────────────────────────────────────────────── */

/* ── BASE RESET ─────────────────────────────────────────────── */
html, body, [class*="css"], .stApp,
.block-container, .element-container,
p, span, div, label, li, td, th {
  font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont,
               'Segoe UI', sans-serif !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}

/* ── PAGE TITLE ─────────────────────────────────────────────── */
h1, .stMarkdown h1 {
  font-size: 24px !important;
  font-weight: 700 !important;
  line-height: 1.25 !important;
  color: #0F172A !important;
  letter-spacing: -0.02em !important;
  margin-bottom: 4px !important;
}

/* ── SECTION HEADER ─────────────────────────────────────────── */
h2, .stMarkdown h2 {
  font-size: 15px !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  color: #1E293B !important;
  letter-spacing: -0.01em !important;
  margin-bottom: 12px !important;
  margin-top: 20px !important;
}

/* ── CARD TITLE ─────────────────────────────────────────────── */
h3, .stMarkdown h3 {
  font-size: 13px !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  color: #334155 !important;
  letter-spacing: 0 !important;
  margin-bottom: 8px !important;
  margin-top: 0 !important;
}

/* ── BODY TEXT ──────────────────────────────────────────────── */
p, .stMarkdown p, .stMarkdown li {
  font-size: 13px !important;
  font-weight: 400 !important;
  line-height: 1.65 !important;
  color: #334155 !important;
  margin-bottom: 6px !important;
}

/* ── SECONDARY / CAPTION TEXT ───────────────────────────────── */
small, .stCaption, [data-testid="stCaptionContainer"] p,
.stMarkdown small {
  font-size: 11px !important;
  font-weight: 400 !important;
  line-height: 1.55 !important;
  color: #64748B !important;
}

/* ── METRIC LABELS (the small ALL-CAPS label above a number) ── */
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] label {
  font-size: 11px !important;
  font-weight: 500 !important;
  line-height: 1.3 !important;
  color: #94A3B8 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.10em !important;
}

/* ── METRIC VALUES (the big number in st.metric) ─────────────── */
[data-testid="stMetricValue"] > div,
[data-testid="stMetricValue"] {
  font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
  font-size: 20px !important;
  font-weight: 600 !important;
  line-height: 1.2 !important;
  color: #0F172A !important;
  letter-spacing: -0.01em !important;
}

/* ── METRIC DELTA (±% change) ────────────────────────────────── */
[data-testid="stMetricDelta"] > div {
  font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
  font-size: 12px !important;
  font-weight: 500 !important;
}

/* ── STOCK PRICE (large display number) ─────────────────────── */
.yiq-price {
  font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
  font-size: 32px !important;
  font-weight: 700 !important;
  line-height: 1.0 !important;
  color: #0F172A !important;
  letter-spacing: -0.02em !important;
}

/* ── PERCENTAGE CHANGE ──────────────────────────────────────── */
.yiq-pct-pos {
  font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  color: #0D7A4E !important;
}
.yiq-pct-neg {
  font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  color: #B91C1C !important;
}

/* ── KEY METRIC NUMBER (e.g. fair value, upside %) ───────────── */
.yiq-metric-num {
  font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
  font-size: 22px !important;
  font-weight: 700 !important;
  line-height: 1.1 !important;
  letter-spacing: -0.01em !important;
}

/* ── LABEL TAG (ALL-CAPS above metric) ──────────────────────── */
.yiq-label {
  font-size: 11px !important;
  font-weight: 500 !important;
  line-height: 1.3 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.11em !important;
  color: #94A3B8 !important;
}

/* ── INSIGHT TEXT ───────────────────────────────────────────── */
.yiq-insight {
  font-size: 15px !important;
  font-weight: 400 !important;
  line-height: 1.7 !important;
  color: #1E293B !important;
}

/* ── SPACING SYSTEM ─────────────────────────────────────────── */
/* Section gap:   24px top/bottom (between major sections)       */
/* Card padding:  20px all sides (compact) / 24px (standard)     */
/* Element gap:   12px (between related items)                   */
/* Tight gap:     6px  (between label and value)                 */

/* Remove excess Streamlit default margins */
.block-container {
  padding-top: 1.5rem !important;
  padding-bottom: 2rem !important;
}
.element-container {
  margin-bottom: 0 !important;
}
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] {
  gap: 0 !important;
}

/* ── BUTTON TEXT ────────────────────────────────────────────── */
.stButton > button {
  font-size: 13px !important;
  font-weight: 500 !important;
  letter-spacing: 0.02em !important;
}

/* ── INPUT / SELECT ─────────────────────────────────────────── */
.stTextInput input,
.stSelectbox select,
.stSelectbox div[data-baseweb="select"] {
  font-size: 13px !important;
  font-weight: 400 !important;
}

/* ── TAB LABELS ─────────────────────────────────────────────── */
[data-testid="stTabs"] button[role="tab"] {
  font-size: 12px !important;
  font-weight: 500 !important;
  letter-spacing: 0.04em !important;
}

/* ── EXPANDER LABELS ─────────────────────────────────────────── */
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {
  font-size: 13px !important;
  font-weight: 500 !important;
  color: #334155 !important;
}

/* ── DATAFRAME / TABLE ──────────────────────────────────────── */
[data-testid="stDataFrame"] *,
.stDataFrame * {
  font-size: 12px !important;
}

/* ── SIDEBAR TEXT ───────────────────────────────────────────── */
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span {
  font-size: 12px !important;
}
section[data-testid="stSidebar"] .stSlider p {
  font-size: 11px !important;
}

/* ── WARNING / INFO BOXES ───────────────────────────────────── */
[data-testid="stAlert"] p {
  font-size: 12px !important;
  line-height: 1.55 !important;
}
</style>
""", unsafe_allow_html=True)


def inject_arrow_fix_js() -> None:
    """Icon text is now hidden by CSS via [data-testid="stIconMaterial"].
    This JS is minimal — only handles edge cases the CSS can't reach."""
    st.markdown("""
<script>
(function() {
  'use strict';

  // Matches Streamlit Material icon text patterns
  function isIcon(t) {
    t = (t || '').trim();
    if (!t) return false;
    return t === '_arrow_right' ||
           t.startsWith('_arrow') ||
           t.startsWith('_expand') ||
           t.startsWith('_chevron') ||
           t.startsWith('keyboard_') ||
           /^_[a-z][a-z_]+$/.test(t);
  }

  // Regex to match icon text patterns anywhere in a string
  var ICON_RX = /(_arrow_right|_arrow_\w+|_expand_\w+|_chevron_\w+|keyboard_double_arrow_\w+|keyboard_\w+)/g;

  function clean() {
    // 1. Hide SVGs in summaries
    document.querySelectorAll(
      '[data-testid="stExpander"] summary svg, details > summary svg'
    ).forEach(function(svg) { svg.style.display = 'none'; });

    // 2. Strip icon text from ALL text nodes and spans inside summaries
    document.querySelectorAll(
      '[data-testid="stExpander"] summary, details > summary'
    ).forEach(function(sum) {
      // Walk all descendant nodes (text + elements)
      var walker = document.createTreeWalker(sum, NodeFilter.SHOW_TEXT);
      var node;
      while (node = walker.nextNode()) {
        var t = node.textContent;
        if (ICON_RX.test(t)) {
          node.textContent = t.replace(ICON_RX, '');
        }
      }
    });

    // 3. Strip stray icon text from body-level spans
    document.querySelectorAll('.stApp span').forEach(function(sp) {
      if (sp.children.length > 0) return; // skip spans with child elements
      var t = sp.textContent || '';
      if (ICON_RX.test(t)) {
        var cleaned = t.replace(ICON_RX, '').trim();
        if (!cleaned) {
          sp.style.cssText = 'font-size:0!important;width:0!important;height:0!important;' +
                             'overflow:hidden!important;position:absolute!important;';
        } else {
          sp.textContent = cleaned;
        }
      }
    });
  }

  clean();
  // Run repeatedly for the first 10 seconds to catch late Streamlit renders
  var _iv = setInterval(clean, 500);
  setTimeout(function() { clearInterval(_iv); }, 10000);
  // Also run on DOM changes
  new MutationObserver(function() { setTimeout(clean, 50); })
    .observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)


def inject_sidebar_nav_css() -> None:
    """Sidebar nav button CSS — moved from app.py."""
    st.markdown("""<style>
/* ── Sidebar nav buttons: base state ── */
section[data-testid="stSidebar"] .stButton > button {
    width: 100% !important;
    background: transparent !important;
    border: none !important;
    border-left: 3px solid transparent !important;
    border-radius: 0px !important;
    color: rgba(255,255,255,0.7) !important;
    text-align: left !important;
    padding: 10px 16px !important;
    font-size: 13px !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.15s ease !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.08) !important;
    color: white !important;
    border-left-color: rgba(29,78,216,0.5) !important;
}
/* Active nav item — primary type */
section[data-testid="stSidebar"] .stButton > button[kind="primaryFormSubmit"],
section[data-testid="stSidebar"] .stButton > button[data-testid*="primary"],
section[data-testid="stSidebar"] .stButton > button[data-testid="baseButton-primary"],
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: rgba(29,78,216,0.15) !important;
    border-left: 3px solid #1D4ED8 !important;
    color: white !important;
    font-weight: 600 !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primaryFormSubmit"]:hover,
section[data-testid="stSidebar"] .stButton > button[data-testid*="primary"]:hover,
section[data-testid="stSidebar"] .stButton > button[data-testid="baseButton-primary"]:hover,
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background: rgba(29,78,216,0.25) !important;
    color: #93C5FD !important;
}
/* Sidebar HR divider */
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.1) !important;
    margin: 8px 0 !important;
}
</style>""", unsafe_allow_html=True)


def inject_theme_css(theme: str) -> None:
    """
    Inject CSS custom-property overrides for dark / light mode.
    Must be called AFTER inject_main_css() so the overrides win.
    Use st.markdown (NOT st.html) so styles reach the parent document.
    """
    if theme == "dark":
        st.markdown("""<style>
/* ── DARK MODE OVERRIDES ─────────────────────────────────────── */
:root {
    --bg-page:       #0F172A !important;
    --bg-card:       #1E293B !important;
    --bg-card2:      #273449 !important;
    --bg-sidebar:    #0A1020 !important;
    --bg-sidebar2:   #060D18 !important;
    --text:          #F1F5F9 !important;
    --text-sec:      #94A3B8 !important;
    --text-muted:    #64748B !important;
    --rule:          #334155 !important;
    --rule2:         #475569 !important;
    --blue-lt:       #1E3A5F !important;
    --blue-glow:     rgba(29,78,216,0.20) !important;
    --green-lt:      #064E3B !important;
    --red-lt:        #450A0A !important;
    --amber-lt:      #451A03 !important;
}

/* App background */
.stApp,
section[data-testid="stAppViewContainer"],
.main .block-container {
    background-color: #0F172A !important;
}

/* Main content area text */
p, span, label, div,
.stMarkdown, .stMarkdown p,
.stText, .element-container {
    color: #F1F5F9 !important;
}

/* Keep signal / brand colors — do NOT override these */
.stMarkdown a, a { color: #60A5FA !important; }

/* Streamlit native widgets */
div[data-testid="stMetric"] {
    background: #1E293B !important;
    border-color: #334155 !important;
}
div[data-testid="stMetric"] label,
div[data-testid="stMetric"] div {
    color: #94A3B8 !important;
}
div[data-testid="stExpander"],
div[data-testid="stExpander"] summary {
    background: #1E293B !important;
    border-color: #334155 !important;
    color: #F1F5F9 !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: #1E293B !important;
    border-color: #334155 !important;
}
.stTabs [data-baseweb="tab"] {
    color: #94A3B8 !important;
}
.stTabs [aria-selected="true"] {
    color: #60A5FA !important;
}
div[data-testid="stSelectbox"] > div,
div[data-testid="stTextInput"] > div > div,
div[data-testid="stNumberInput"] > div > div,
div[data-testid="stTextArea"] > div > div {
    background: #1E293B !important;
    border-color: #334155 !important;
    color: #F1F5F9 !important;
}
div[data-testid="stForm"] {
    background: #1E293B !important;
    border-color: #334155 !important;
}

/* Plotly chart backgrounds already transparent — no override needed */

/* Scrollbar */
::-webkit-scrollbar-track { background: #0F172A; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
</style>""", unsafe_allow_html=True)

    else:
        # Light mode — restore defaults (in case of runtime toggle)
        st.markdown("""<style>
/* ── LIGHT MODE RESTORE ──────────────────────────────────────── */
:root {
    --bg-page:    #EEF2F8;
    --bg-card:    #FFFFFF;
    --bg-card2:   #F7F9FC;
    --text:       #0F172A;
    --text-sec:   #475569;
    --text-muted: #94A3B8;
    --rule:       #E2E8F0;
    --rule2:      #CBD5E1;
    --blue-lt:    #EFF6FF;
    --green-lt:   #ECFDF5;
    --red-lt:     #FEF2F2;
    --amber-lt:   #FFFBEB;
}
.stApp,
section[data-testid="stAppViewContainer"],
.main .block-container {
    background-color: #EEF2F8 !important;
}
</style>""", unsafe_allow_html=True)


def inject_all() -> None:
    inject_fonts()
    inject_main_css()
    inject_typography_css()
    inject_arrow_fix_js()
    inject_sidebar_nav_css()
