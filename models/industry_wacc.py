# models/industry_wacc.py
# ═══════════════════════════════════════════════════════════════
# INDUSTRY ASSUMPTIONS ENGINE v2
# ═══════════════════════════════════════════════════════════════
# Sources: Damodaran NYU data (India/Emerging Markets)
# Updated for Indian market conditions (INR, RBI rates)
#
# NEW in v2:
#   1. capex_intensity   — how much of revenue goes to capex
#   2. wc_intensity      — working capital as % of revenue
#   3. rd_expense_pct    — R&D as % of revenue (pharma heavy)
#   4. depreciation_pct  — D&A as % of revenue
#   5. FCF adjustment    — sector-specific NOPAT → FCF conversion
#   6. Airlines sector   — added with lease liability treatment
#   7. Infrastructure    — added with project-based adjustments
#   8. max/min growth    — revenue and FCF growth guardrails
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
# INDUSTRY ASSUMPTIONS TABLE
# ══════════════════════════════════════════════════════════════
#
# capex_intensity    : Capex as % of Revenue (maintenance + growth)
# wc_days            : Working Capital Days (higher = more cash tied up)
# wc_pct_revenue     : Working Capital as % of Revenue
# rd_pct_revenue     : R&D Expense as % of Revenue
# depreciation_pct   : D&A as % of Revenue
# fcf_conv_factor    : NOPAT → FCF conversion (accounts for capex drain)
#                      Lower = more capex intensive
# rev_growth_max     : Maximum realistic revenue growth
# rev_growth_min     : Minimum realistic revenue growth
# fcf_growth_max     : Maximum realistic FCF growth
# notes              : Key valuation notes for analyst

INDUSTRY_WACC = {

    # ── Airlines ─────────────────────────────────────────────
    "airlines": {
        "wacc_min":         0.10, "wacc_max": 0.13, "wacc_default": 0.115,
        "terminal_growth":  0.025,
        "beta_typical":     1.35,
        "capex_intensity":  0.18,    # 18% of revenue — aircraft purchases
        "wc_days":          -15,     # negative WC is common (advance bookings)
        "wc_pct_revenue":  -0.04,    # airlines get paid before service
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.09,    # high D&A on aircraft
        "fcf_conv_factor":  0.45,    # very capex heavy → only 45% NOPAT → FCF
        "rev_growth_max":   0.12,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.12,
        "description":      "Airlines — high capex, lease liabilities, fuel risk",
        "notes":            "Include aircraft lease liabilities as debt. Heavy capex cycle. Fuel cost sensitivity.",
        "keywords":         ["interglobe","indigo","spicejet","airasia","vistara",
                             "airindia","goair","akasaair"],
    },

    # ── IT & Technology ───────────────────────────────────────
    "it_services": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.035,
        "beta_typical":     1.05,
        "capex_intensity":  0.02,    # 2% of revenue — very asset-light
        "wc_days":          45,
        "wc_pct_revenue":   0.08,
        "rd_pct_revenue":   0.01,    # minimal formal R&D
        "depreciation_pct": 0.02,
        "fcf_conv_factor":  0.88,    # asset-light → 88% NOPAT converts to FCF
        "rev_growth_max":   0.20,
        "rev_growth_min":   0.03,
        "fcf_growth_max":   0.20,
        "description":      "IT Services — asset-light, high margins, stable cash flows",
        "notes":            "Low capex intensity. Employee costs are main expense. USD revenue exposure.",
        "keywords":         ["tcs","infy","wipro","hcltech","techm","ltim","persistent",
                             "coforge","mphasis","kpittech","tataelxsi","cyient",
                             "zensar","mastek","niit","ofss","hexaware","ltimindtr",
                             "cmsinfo","cigniti","rsystems","bsoft","niitmts","gipcl",
                             "tanla","route","justdial","pacedigitk"],
    },
    "saas_software": {
        "wacc_min":         0.08, "wacc_max": 0.10, "wacc_default": 0.09,
        "terminal_growth":  0.04,
        "beta_typical":     1.10,
        "capex_intensity":  0.03,
        "wc_days":          -30,     # SaaS gets paid upfront (deferred revenue)
        "wc_pct_revenue":  -0.05,
        "rd_pct_revenue":   0.15,    # high R&D
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.85,
        "rev_growth_max":   0.30,
        "rev_growth_min":   0.05,
        "fcf_growth_max":   0.30,
        "description":      "SaaS/Software — high growth, asset-light, subscription revenue",
        "notes":            "Low WACC justified by recurring revenue. High R&D. Negative WC is good (advance payments).",
        "keywords":         ["intellect","tally","newgen","rapidflue","zoho"],
    },
    "tech_hardware": {
        "wacc_min":         0.11, "wacc_max": 0.13, "wacc_default": 0.12,
        "terminal_growth":  0.03,
        "beta_typical":     1.15,
        "capex_intensity":  0.06,
        "wc_days":          60,
        "wc_pct_revenue":   0.12,
        "rd_pct_revenue":   0.03,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.72,
        "rev_growth_max":   0.25,
        "rev_growth_min":   0.02,
        "fcf_growth_max":   0.22,
        "description":      "Tech Hardware/Electronics — moderate capex, cyclical",
        "notes":            "Supply chain risk. Component cost cycles. Inventory management critical.",
        "keywords":         ["dixon","amber","kaynes","syrma","pgel","avalon"],
    },

    # ── FMCG & Consumer ───────────────────────────────────────
    "fmcg": {
        "wacc_min":         0.09, "wacc_max": 0.11, "wacc_default": 0.10,
        "terminal_growth":  0.04,
        "beta_typical":     0.75,
        "capex_intensity":  0.03,    # 3% of revenue — low capex
        "wc_days":          30,
        "wc_pct_revenue":   0.05,
        "rd_pct_revenue":   0.005,
        "depreciation_pct": 0.025,
        "fcf_conv_factor":  0.88,    # stable business → high FCF conversion
        "rev_growth_max":   0.15,
        "rev_growth_min":   0.04,
        "fcf_growth_max":   0.14,
        "description":      "FMCG — stable demand, pricing power, low risk",
        "notes":            "Lowest risk sector. Defensive. Pricing power protects margins. Low capex = high FCF.",
        "keywords":         ["hindunilvr","itc","nestle","britannia","dabur","marico",
                             "colpal","godrejcp","emami","jyothy","bajajcon","pghh",
                             "gillette","vstind","godfryphlp","patanjali","tataconsum",
                             "jyothylab","emamiltd"],
    },
    "consumer_durable": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.035,
        "beta_typical":     0.95,
        "capex_intensity":  0.04,
        "wc_days":          45,
        "wc_pct_revenue":   0.08,
        "rd_pct_revenue":   0.01,
        "depreciation_pct": 0.03,
        "fcf_conv_factor":  0.80,
        "rev_growth_max":   0.18,
        "rev_growth_min":   0.03,
        "fcf_growth_max":   0.16,
        "description":      "Consumer Durables — discretionary, moderate risk",
        "notes":            "Seasonal demand. Distribution moat. Higher WC than pure FMCG.",
        "keywords":         ["havells","voltas","bluestar","whirlpool","vguard",
                             "crompton","orient","bajajele"],
    },

    # ── Pharma & Healthcare ───────────────────────────────────
    "pharma": {
        "wacc_min":         0.10, "wacc_max": 0.13, "wacc_default": 0.115,
        "terminal_growth":  0.035,
        "beta_typical":     0.85,
        "capex_intensity":  0.07,    # 7% — API plants + formulation
        "wc_days":          90,      # high inventory + receivables
        "wc_pct_revenue":   0.18,
        "rd_pct_revenue":   0.08,    # HIGH R&D — 8% of revenue
        "depreciation_pct": 0.05,
        "fcf_conv_factor":  0.72,    # R&D + capex reduce FCF significantly
        "rev_growth_max":   0.18,
        "rev_growth_min":   0.04,
        "fcf_growth_max":   0.18,
        "description":      "Pharma — R&D risk, regulatory risk, export dependence",
        "notes":            "R&D expense reduces near-term FCF but builds pipeline value. US FDA risk. High WC due to inventory.",
        "keywords":         ["sunpharma","drreddy","cipla","lupin","auropharma","divislab",
                             "torntpharm","alkem","biocon","glenmark","ipca","natco",
                             "granules","lauruslabs","strides","mankind","jbchepharm",
                             "wockpharma","solara","sequent","suven","zyduslife","abbotindia",
                             "pfizer","sanofi","glaxo","ipcalab","rpglife","fdc",
                             "indramedco","marksans"],
    },
    "hospital": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.04,
        "beta_typical":     0.90,
        "capex_intensity":  0.09,    # 9% — medical equipment + expansion
        "wc_days":          20,
        "wc_pct_revenue":   0.04,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.07,
        "fcf_conv_factor":  0.65,    # heavy capex for expansion
        "rev_growth_max":   0.20,
        "rev_growth_min":   0.05,
        "fcf_growth_max":   0.18,
        "description":      "Hospitals — asset-heavy but stable demand",
        "notes":            "Long gestation on new hospitals. Mature beds = high FCF. High depreciation on equipment.",
        "keywords":         ["apollohosp","fortis","maxhealth","narayana","aster",
                             "kims","rainbow","yatharth","nhc","sagility","lalpathlab",
                             "metropolis","thyrocare","medplus"],
    },

    # ── Auto & Manufacturing ──────────────────────────────────
    "auto_oem": {
        "wacc_min":         0.11, "wacc_max": 0.13, "wacc_default": 0.12,
        "terminal_growth":  0.03,
        "beta_typical":     1.10,
        "capex_intensity":  0.08,    # 8% — plant + tooling
        "wc_days":          25,
        "wc_pct_revenue":   0.05,
        "rd_pct_revenue":   0.03,    # EV transition R&D
        "depreciation_pct": 0.05,
        "fcf_conv_factor":  0.68,    # capex-heavy
        "rev_growth_max":   0.20,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.18,
        "description":      "Auto OEM — capex-heavy, cyclical demand",
        "notes":            "EV transition increases near-term capex. Cyclical. High WC variability.",
        "keywords":         ["maruti","tatamotors","mahindra","m&m","bajaj-auto","heromotoco",
                             "tvsmotor","eichermot","ashokley","escorts","swarajeng",
                             "royalenf","bajajauto"],
    },
    "auto_ancillary": {
        "wacc_min":         0.11, "wacc_max": 0.13, "wacc_default": 0.12,
        "terminal_growth":  0.03,
        "beta_typical":     1.05,
        "capex_intensity":  0.06,
        "wc_days":          45,
        "wc_pct_revenue":   0.09,
        "rd_pct_revenue":   0.02,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.70,
        "rev_growth_max":   0.18,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.16,
        "description":      "Auto Components — dependent on OEM cycle",
        "notes":            "Revenue follows OEM volumes. EV transition creates component mix shift.",
        "keywords":         ["motherson","boschltd","bharatforg","endurance","sundrmfast",
                             "minda","lumaxtech","unominda","suprajit","skfindia","timken",
                             "schaeffler","greavescot","craftsman","wabcoindia","mahindcie",
                             "nrb","fmgoetze"],
    },

    # ── Capital Goods & Industrials ───────────────────────────
    "capital_goods": {
        "wacc_min":         0.11, "wacc_max": 0.13, "wacc_default": 0.12,
        "terminal_growth":  0.035,
        "beta_typical":     1.10,
        "capex_intensity":  0.05,
        "wc_days":          90,      # high WC — long project cycles
        "wc_pct_revenue":   0.20,    # large receivables/advances
        "rd_pct_revenue":   0.02,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.60,    # WC ties up cash during projects
        "rev_growth_max":   0.20,
        "rev_growth_min":   0.02,
        "fcf_growth_max":   0.18,
        "description":      "Capital Goods — project-based, order-book dependent",
        "notes":            "Order book visibility is key. High WC due to project billing cycles. Lumpy FCF.",
        "keywords":         ["lt","siemens","abb","bhel","thermax","cumminsind",
                             "kirloseng","elgiequip","ingersrand","kec","kalpatpowr",
                             "powermech","isgec","gmmpfaudlr","laxmimach","cmsinfo",
                             "cyient","bbल","pokarna","sswl","eiel","ramcoind",
                             "balmlawrie","maninfra","jkil","geship","tvshltd","rvnl",
                             "ircon","rites","grinfra","nbcc"],
    },
    "defence": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.04,
        "beta_typical":     0.90,
        "capex_intensity":  0.06,
        "wc_days":          120,     # very long project cycles
        "wc_pct_revenue":   0.25,
        "rd_pct_revenue":   0.05,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.55,    # advance payments offset by long cycles
        "rev_growth_max":   0.20,
        "rev_growth_min":   0.05,
        "fcf_growth_max":   0.18,
        "description":      "Defence — government contracts, stable but lumpy",
        "notes":            "Government sole buyer. Long order-to-revenue cycle. Indigenisation tailwind.",
        "keywords":         ["hal","bel","beml","cochinship","grse","mazagon",
                             "paras","data"],
    },

    # ── Infrastructure ────────────────────────────────────────
    "infrastructure": {
        "wacc_min":         0.10, "wacc_max": 0.13, "wacc_default": 0.115,
        "terminal_growth":  0.03,
        "beta_typical":     1.05,
        "capex_intensity":  0.20,    # 20% — massive infra build
        "wc_days":          60,
        "wc_pct_revenue":   0.12,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.08,
        "fcf_conv_factor":  0.45,    # very capex heavy
        "rev_growth_max":   0.15,
        "rev_growth_min":   0.03,
        "fcf_growth_max":   0.12,
        "description":      "Infrastructure/Construction — high capex, project-based",
        "notes":            "Leverage is structural. Concession-based revenues provide visibility. Very high capex.",
        "keywords":         ["gmrairport","adaniairpo","adaniports","adanient",
                             "hudco","irfc","indigrid","pfc","recltd","ncc"],
    },

    # ── Energy & Oil ──────────────────────────────────────────
    "oil_gas": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.025,
        "beta_typical":     0.95,
        "capex_intensity":  0.15,    # 15% — exploration + production
        "wc_days":          35,
        "wc_pct_revenue":   0.07,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.08,    # high D&A on wells/assets
        "fcf_conv_factor":  0.58,    # commodity cycle + heavy capex
        "rev_growth_max":   0.10,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.10,
        "description":      "Oil & Gas — commodity price risk, government influence",
        "notes":            "Commodity cycle drives revenue. Heavy upstream capex. Government pricing controls in India.",
        "keywords":         ["reliance","ongc","bpcl","hindpetro","ioc","castrolind",
                             "gulfoillub","gail","petronet","atgl","mgl","igl","gspl",
                             "gujgasltd","mahangas","coalindia"],
    },
    "power": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.105,
        "terminal_growth":  0.03,
        "beta_typical":     0.85,
        "capex_intensity":  0.18,    # 18% — plant construction
        "wc_days":          60,
        "wc_pct_revenue":   0.12,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.10,
        "fcf_conv_factor":  0.50,    # high capex, regulated returns
        "rev_growth_max":   0.12,
        "rev_growth_min":   0.02,
        "fcf_growth_max":   0.10,
        "description":      "Power/Utilities — regulated, stable but capital-heavy",
        "notes":            "Regulated ROE. Long asset life. High leverage is structural. Renewable capex cycle.",
        "keywords":         ["ntpc","powergrid","tatapower","adanigreen","adanitrans",
                             "cesc","torntpower","nhpc","sjvn","thdc","adaniensol",
                             "indigrid","suzlon","inoxwind","websol"],
    },

    # ── Metals & Mining ───────────────────────────────────────
    "metals": {
        "wacc_min":         0.12, "wacc_max": 0.15, "wacc_default": 0.13,
        "terminal_growth":  0.025,
        "beta_typical":     1.30,
        "capex_intensity":  0.12,    # 12% — smelters + mining
        "wc_days":          55,
        "wc_pct_revenue":   0.11,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.07,
        "fcf_conv_factor":  0.60,
        "rev_growth_max":   0.15,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.15,
        "description":      "Metals/Mining — highly cyclical, commodity price sensitive",
        "notes":            "Commodity cycle is dominant driver. High leverage common. China demand sensitivity.",
        "keywords":         ["tatasteel","jswsteel","sail","hindalco","vedl","nmdc",
                             "hindcopper","nationalum","ratnamani","welcorp","aplapollo",
                             "jspl","moil","tinplate","hscl","ksl","ghcl","upl",
                             "epigral"],
    },

    # ── Cement ────────────────────────────────────────────────
    "cement": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.035,
        "beta_typical":     0.95,
        "capex_intensity":  0.10,    # 10% — kiln + grinding
        "wc_days":          20,
        "wc_pct_revenue":   0.04,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.08,
        "fcf_conv_factor":  0.65,
        "rev_growth_max":   0.15,
        "rev_growth_min":   0.02,
        "fcf_growth_max":   0.14,
        "description":      "Cement — capex-heavy, regional pricing power",
        "notes":            "Infrastructure capex and housing drive demand. Regional pricing. Energy cost sensitivity.",
        "keywords":         ["ultracemco","ambujacement","acc","shreecem","dalmia",
                             "jkcement","ramcocem","heidelberg","birlacorpn","prism",
                             "starcement","jswcement","nuvoco","indiacem","dalmiasug"],
    },

    # ── Real Estate ───────────────────────────────────────────
    "realty": {
        "wacc_min":         0.12, "wacc_max": 0.15, "wacc_default": 0.13,
        "terminal_growth":  0.03,
        "beta_typical":     1.35,
        "capex_intensity":  0.25,    # 25% — land + construction
        "wc_days":          300,     # massive WC — project takes years
        "wc_pct_revenue":   0.35,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.02,
        "fcf_conv_factor":  0.40,    # very WC and capex intensive
        "rev_growth_max":   0.20,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.15,
        "description":      "Real Estate — high leverage, project risk, illiquidity",
        "notes":            "Pre-sales are key. RERA compliance. Leverage is high. Long WC cycle.",
        "keywords":         ["dlf","godrejprop","oberoi","prestige","phoenix","brigade",
                             "mahlife","sobha","koltepatil","sunteck","ganeshhou"],
    },

    # ── Telecom ───────────────────────────────────────────────
    "telecom": {
        "wacc_min":         0.11, "wacc_max": 0.13, "wacc_default": 0.12,
        "terminal_growth":  0.03,
        "beta_typical":     1.05,
        "capex_intensity":  0.20,    # 20% — spectrum + towers + 5G
        "wc_days":          -10,     # telecom gets paid monthly
        "wc_pct_revenue":  -0.02,
        "rd_pct_revenue":   0.01,
        "depreciation_pct": 0.12,    # high D&A on spectrum + network
        "fcf_conv_factor":  0.50,    # spectrum capex is huge
        "rev_growth_max":   0.12,
        "rev_growth_min":   0.02,
        "fcf_growth_max":   0.12,
        "description":      "Telecom — capital-intensive, spectrum costs, moderate risk",
        "notes":            "5G capex cycle. Spectrum amortisation is key. ARPU growth drives FCF inflection.",
        "keywords":         ["bhartiartl","vodafone","rcom","tatacomm","railtel",
                             "sterlite","hfcl","tejas","mpsltd","dbcorp"],
    },

    # ── Retail ────────────────────────────────────────────────
    "retail": {
        "wacc_min":         0.11, "wacc_max": 0.13, "wacc_default": 0.12,
        "terminal_growth":  0.04,
        "beta_typical":     1.10,
        "capex_intensity":  0.04,    # 4% — store fit-outs
        "wc_days":          -5,      # retail paid upfront
        "wc_pct_revenue":  -0.01,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.75,
        "rev_growth_max":   0.20,
        "rev_growth_min":   0.03,
        "fcf_growth_max":   0.18,
        "description":      "Retail — working capital intensive, competitive",
        "notes":            "Negative WC is structural advantage. Store expansion drives capex. Inventory management key.",
        "keywords":         ["dmart","trent","abfrl","manyavar","vmart","shoperstop",
                             "spencers","vedant","campus","metro","senco","kalyan",
                             "titan","pcjeweller","rajeshexpo"],
    },

    # ── Chemicals ────────────────────────────────────────────
    "chemicals": {
        "wacc_min":         0.11, "wacc_max": 0.13, "wacc_default": 0.12,
        "terminal_growth":  0.035,
        "beta_typical":     1.10,
        "capex_intensity":  0.09,    # 9% — reactors + plants
        "wc_days":          75,
        "wc_pct_revenue":   0.15,
        "rd_pct_revenue":   0.03,
        "depreciation_pct": 0.06,
        "fcf_conv_factor":  0.65,
        "rev_growth_max":   0.18,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.16,
        "description":      "Specialty Chemicals — export-linked, moderate risk",
        "notes":            "China+1 strategy beneficiary. Cyclical margins. High WC due to export receivables.",
        "keywords":         ["atul","deepakntr","srf","gnfc","coromandel","pi",
                             "bayer","dhanuka","rallis","sumichem","insecticid",
                             "pidilitind","vinati","navin","clean","tatachem"],
    },

    # ── Media & Entertainment ─────────────────────────────────
    "media": {
        "wacc_min":         0.12, "wacc_max": 0.14, "wacc_default": 0.13,
        "terminal_growth":  0.025,
        "beta_typical":     1.20,
        "capex_intensity":  0.04,
        "wc_days":          30,
        "wc_pct_revenue":   0.06,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.05,
        "fcf_conv_factor":  0.70,
        "rev_growth_max":   0.15,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.12,
        "description":      "Media — disruption risk, high volatility",
        "notes":            "OTT disruption risk. Advertising cyclicality. Content cost inflation.",
        "keywords":         ["zeel","pvrinox","nazara","tipsmusic","saregama"],
    },

    # ── Logistics ────────────────────────────────────────────
    "logistics": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.04,
        "beta_typical":     0.95,
        "capex_intensity":  0.08,    # 8% — fleet + warehouses
        "wc_days":          35,
        "wc_pct_revenue":   0.07,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.06,
        "fcf_conv_factor":  0.68,
        "rev_growth_max":   0.20,
        "rev_growth_min":   0.03,
        "fcf_growth_max":   0.18,
        "description":      "Logistics — asset-heavy but growing sector",
        "notes":            "E-commerce tailwind. Asset-heavy model. Last-mile is competitive.",
        "keywords":         ["irctc","delhivery","bluedart","tci","gmrairport",
                             "adaniairpo","interglobe","rvnl","ircon","irfc","rites"],
    },

    # ── General Fallback ─────────────────────────────────────
    "general": {
        "wacc_min":         0.10, "wacc_max": 0.13, "wacc_default": 0.115,
        "terminal_growth":  0.03,
        "beta_typical":     1.00,
        "capex_intensity":  0.05,
        "wc_days":          45,
        "wc_pct_revenue":   0.09,
        "rd_pct_revenue":   0.01,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.72,
        "rev_growth_max":   0.20,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.18,
        "description":      "General/Diversified — market average assumptions",
        "notes":            "Default sector. Apply manual review.",
        "keywords":         [],
    },
}


# ══════════════════════════════════════════════════════════════
# SECTOR DETECTOR
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# USA INDUSTRY WACC TABLE
# ══════════════════════════════════════════════════════════════
# Sources: Damodaran NYU (US market)
# Risk-free rate: ~4.3% (10Y UST), ERP: ~5.5% (Damodaran 2025)
# Lower WACC than India — lower risk-free rate + no country risk
# ══════════════════════════════════════════════════════════════

INDUSTRY_WACC_USA = {

    # ── Big Tech / Mega-cap ───────────────────────────────────
    "us_mega_tech": {
        "wacc_min":         0.08, "wacc_max": 0.10, "wacc_default": 0.093,
        "terminal_growth":  0.030,   # US long-run nominal GDP ~2.1% + tech premium
        "beta_typical":     1.25,
        "capex_intensity":  0.05,
        "wc_days":          -20,
        "wc_pct_revenue":  -0.04,
        "rd_pct_revenue":   0.15,
        "depreciation_pct": 0.05,
        "fcf_conv_factor":  0.88,
        "rev_growth_max":   0.50,
        "rev_growth_min":   0.05,
        "fcf_growth_max":   0.50,
        "description":      "US Mega-cap Tech — FAANG/MAMN, massive FCF, global moat",
        "notes":            "Network effects + platform moat justify low WACC. High R&D. Buyback machines.",
        "keywords":         ["aapl","msft","googl","goog","meta","amzn","nvda","nflx"],
    },

    # ── US IT Services & Enterprise Software ─────────────────
    "us_it_services": {
        "wacc_min":         0.07, "wacc_max": 0.10, "wacc_default": 0.091,
        "terminal_growth":  0.030,
        "beta_typical":     1.10,
        "capex_intensity":  0.03,
        "wc_days":          30,
        "wc_pct_revenue":   0.06,
        "rd_pct_revenue":   0.12,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.85,
        "rev_growth_max":   0.22,
        "rev_growth_min":   0.03,
        "fcf_growth_max":   0.22,
        "description":      "US IT Services / Enterprise Software — asset-light, recurring revenue",
        "notes":            "SaaS transition = higher recurring revenue. High R&D. Low capex. Buybacks common.",
        "keywords":         ["acn","crm","orcl","intu","adbe","now","ibm","csco","sap"],
    },

    # ── US Semiconductors ─────────────────────────────────────
    "us_semiconductors": {
        "wacc_min":         0.09, "wacc_max": 0.12, "wacc_default": 0.103,
        "terminal_growth":  0.030,
        "beta_typical":     1.25,
        "capex_intensity":  0.12,
        "wc_days":          60,
        "wc_pct_revenue":   0.12,
        "rd_pct_revenue":   0.20,
        "depreciation_pct": 0.08,
        "fcf_conv_factor":  0.72,
        "rev_growth_max":   0.30,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.28,
        "description":      "US Semiconductors — cyclical but high-moat, heavy R&D",
        "notes":            "Fabless (NVDA, AMD, QCOM) have higher FCF conversion. AI cycle tailwind. High R&D is investment.",
        "keywords":         ["nvda","amd","intc","qcom","txn","avgo","mu","mrvl","on","mpwr","klac","lam","amat","asml"],
    },

    # ── US Consumer Staples ───────────────────────────────────
    "us_consumer_staples": {
        "wacc_min":         0.06, "wacc_max": 0.09, "wacc_default": 0.074,
        "terminal_growth":  0.025,
        "beta_typical":     0.60,
        "capex_intensity":  0.04,
        "wc_days":          20,
        "wc_pct_revenue":   0.04,
        "rd_pct_revenue":   0.01,
        "depreciation_pct": 0.03,
        "fcf_conv_factor":  0.87,
        "rev_growth_max":   0.10,
        "rev_growth_min":   0.01,
        "fcf_growth_max":   0.10,
        "description":      "US Consumer Staples — defensive, pricing power, dividend payers",
        "notes":            "Low beta. Steady cash flows. Brand pricing power (KO, PG, PEP). Low WACC justified.",
        "keywords":         ["ko","pep","pg","cl","gis","k","mo","pm","cost","wmt","tgt","kr","sbux"],
    },

    # ── US Consumer Discretionary ─────────────────────────────
    "us_consumer_disc": {
        "wacc_min":         0.08, "wacc_max": 0.11, "wacc_default": 0.094,
        "terminal_growth":  0.025,
        "beta_typical":     1.10,
        "capex_intensity":  0.05,
        "wc_days":          -10,
        "wc_pct_revenue":  -0.02,
        "rd_pct_revenue":   0.01,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.78,
        "rev_growth_max":   0.20,
        "rev_growth_min":  -0.08,
        "fcf_growth_max":   0.18,
        "description":      "US Consumer Discretionary — cyclical, brand-driven",
        "notes":            "Interest rate sensitive. Retail negative WC is advantage. More cyclical than staples.",
        "keywords":         ["tsla","nke","sbux","mcd","hd","low","f","gm","tjx","ross","bkng","abnb"],
    },

    # ── US Pharma / Biotech ───────────────────────────────────
    "us_pharma": {
        "wacc_min":         0.07, "wacc_max": 0.10, "wacc_default": 0.082,
        "terminal_growth":  0.025,
        "beta_typical":     0.80,
        "capex_intensity":  0.05,
        "wc_days":          60,
        "wc_pct_revenue":   0.12,
        "rd_pct_revenue":   0.18,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.72,
        "rev_growth_max":   0.20,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.18,
        "description":      "US Pharma / Biotech — pipeline risk, FDA risk, high R&D",
        "notes":            "Patent cliff risk. Pipeline optionality not in DCF. Pricing pressure from IRA. R&D is investment.",
        "keywords":         ["jnj","pfe","mrk","abbv","lly","amgn","bmy","gild","biib","regn","vrtx","zts","mrna"],
    },

    # ── US Healthcare Services ────────────────────────────────
    "us_healthcare_services": {
        "wacc_min":         0.07, "wacc_max": 0.10, "wacc_default": 0.079,
        "terminal_growth":  0.025,
        "beta_typical":     0.85,
        "capex_intensity":  0.04,
        "wc_days":          25,
        "wc_pct_revenue":   0.05,
        "rd_pct_revenue":   0.01,
        "depreciation_pct": 0.03,
        "fcf_conv_factor":  0.80,
        "rev_growth_max":   0.15,
        "rev_growth_min":   0.02,
        "fcf_growth_max":   0.14,
        "description":      "US Healthcare Services — managed care, stable earnings",
        "notes":            "Low capex. Managed care (UNH, CI) = high FCF. Aging population tailwind.",
        "keywords":         ["unh","cvs","ci","aet","hum","hca","tmo","abt","dhr","bax","iqv"],
    },

    # ── US Banks & Financials ─────────────────────────────────
    "us_banks": {
        "wacc_min":         0.08, "wacc_max": 0.12, "wacc_default": 0.098,
        "terminal_growth":  0.025,
        "beta_typical":     1.10,
        "capex_intensity":  0.03,
        "wc_days":          0,
        "wc_pct_revenue":   0.0,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.02,
        "fcf_conv_factor":  0.70,
        "rev_growth_max":   0.15,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.15,
        "description":      "US Banks & Financials — interest rate sensitive, DCF less reliable",
        "notes":            "Use P/Book and P/E crosscheck. NIM sensitivity. Regulatory capital requirements.",
        "keywords":         ["jpm","bac","wfc","c","gs","ms","schw","blk","axp","v","ma","pypl","sq","cb","brk"],
    },

    # ── US Energy ─────────────────────────────────────────────
    "us_energy": {
        "wacc_min":         0.08, "wacc_max": 0.12, "wacc_default": 0.096,
        "terminal_growth":  0.020,
        "beta_typical":     1.05,
        "capex_intensity":  0.15,
        "wc_days":          35,
        "wc_pct_revenue":   0.07,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.10,
        "fcf_conv_factor":  0.58,
        "rev_growth_max":   0.12,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.12,
        "description":      "US Energy — commodity price cycle, heavy upstream capex",
        "notes":            "Oil price dominant driver. Permian basin = lower breakeven. Shale variable cost flexibility.",
        "keywords":         ["xom","cvx","cop","eog","pio","slb","hal","bkr","vlo","psx","mpc","hes","dvn"],
    },

    # ── US Industrials / Aerospace & Defence ──────────────────
    "us_industrials": {
        "wacc_min":         0.07, "wacc_max": 0.10, "wacc_default": 0.087,
        "terminal_growth":  0.025,
        "beta_typical":     1.00,
        "capex_intensity":  0.05,
        "wc_days":          60,
        "wc_pct_revenue":   0.12,
        "rd_pct_revenue":   0.03,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.72,
        "rev_growth_max":   0.15,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.14,
        "description":      "US Industrials — diversified manufacturing, defence, logistics",
        "notes":            "Aerospace & defence = government contracts. Long order books. Reshoring tailwind.",
        "keywords":         ["hon","rtx","lmt","noc","gd","ba","cat","de","ups","fdx","emr","etn","mmm","ge","ir","otis","carr"],
    },

    # ── US Utilities ──────────────────────────────────────────
    "us_utilities": {
        "wacc_min":         0.06, "wacc_max": 0.09, "wacc_default": 0.073,
        "terminal_growth":  0.020,
        "beta_typical":     0.55,
        "capex_intensity":  0.20,
        "wc_days":          30,
        "wc_pct_revenue":   0.06,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.10,
        "fcf_conv_factor":  0.45,
        "rev_growth_max":   0.08,
        "rev_growth_min":   0.01,
        "fcf_growth_max":   0.07,
        "description":      "US Utilities — regulated, rate-base growth, high capex",
        "notes":            "Regulated ROE (~9-10%). Data center power demand = new tailwind. Bond proxy.",
        "keywords":         ["nee","duk","so","d","aep","exc","ed","xel","peg","pcg","awk","es","etr"],
    },

    # ── US REITs ──────────────────────────────────────────────
    "us_reits": {
        "wacc_min":         0.06, "wacc_max": 0.09, "wacc_default": 0.079,
        "terminal_growth":  0.025,
        "beta_typical":     0.80,
        "capex_intensity":  0.10,
        "wc_days":          0,
        "wc_pct_revenue":   0.0,
        "rd_pct_revenue":   0.00,
        "depreciation_pct": 0.12,
        "fcf_conv_factor":  0.60,
        "rev_growth_max":   0.12,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.10,
        "description":      "US REITs — income-oriented, rate sensitive, use FFO not FCF",
        "notes":            "Value using FFO/AFFO. High depreciation inflates GAAP earnings. Rate sensitive.",
        "keywords":         ["pld","amt","eqix","spg","o","dlr","avb","eqr","are","bxp","vno","cci","sbac"],
    },

    # ── US Materials ──────────────────────────────────────────
    "us_materials": {
        "wacc_min":         0.08, "wacc_max": 0.12, "wacc_default": 0.097,
        "terminal_growth":  0.020,
        "beta_typical":     1.15,
        "capex_intensity":  0.10,
        "wc_days":          55,
        "wc_pct_revenue":   0.11,
        "rd_pct_revenue":   0.02,
        "depreciation_pct": 0.07,
        "fcf_conv_factor":  0.62,
        "rev_growth_max":   0.12,
        "rev_growth_min":  -0.10,
        "fcf_growth_max":   0.12,
        "description":      "US Materials — commodity cycle, China demand sensitivity",
        "notes":            "Commodity price is dominant driver. Nearshoring boosts US chemicals.",
        "keywords":         ["fcx","nem","nue","stld","clf","x","aa","dd","dow","lyb","lin","apd","ecl","ppg"],
    },

    # ── US Communication Services ─────────────────────────────
    "us_communication": {
        "wacc_min":         0.07, "wacc_max": 0.11, "wacc_default": 0.089,
        "terminal_growth":  0.020,
        "beta_typical":     0.90,
        "capex_intensity":  0.18,
        "wc_days":          -10,
        "wc_pct_revenue":  -0.02,
        "rd_pct_revenue":   0.01,
        "depreciation_pct": 0.12,
        "fcf_conv_factor":  0.52,
        "rev_growth_max":   0.10,
        "rev_growth_min":  -0.03,
        "fcf_growth_max":   0.10,
        "description":      "US Telecom — 5G capex cycle, subscription model, high D&A",
        "notes":            "5G investment weighs on FCF. Streaming wars for media. Spectrum = high capex.",
        "keywords":         ["t","vz","cmcsa","dis","nflx","wbd","para","fox","lumn","chtr"],
    },

    # ── US General Fallback ───────────────────────────────────
    "us_general": {
        "wacc_min":         0.07, "wacc_max": 0.11, "wacc_default": 0.090,
        "terminal_growth":  0.025,
        "beta_typical":     1.00,
        "capex_intensity":  0.05,
        "wc_days":          45,
        "wc_pct_revenue":   0.09,
        "rd_pct_revenue":   0.02,
        "depreciation_pct": 0.04,
        "fcf_conv_factor":  0.72,
        "rev_growth_max":   0.20,
        "rev_growth_min":  -0.05,
        "fcf_growth_max":   0.18,
        "description":      "US General — S&P 500 average assumptions",
        "notes":            "Default US sector. Lower WACC than India due to risk-free rate differential.",
        "keywords":         [],
    },
}

# Combined lookup: try US table first for US tickers, then India table
_ALL_WACC = {**INDUSTRY_WACC, **INDUSTRY_WACC_USA}


def _is_us_ticker(ticker: str) -> bool:
    """Return True for US tickers (no .NS/.BO suffix and not other foreign suffixes)."""
    t = ticker.upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return False
    FOREIGN = [".L", ".PA", ".DE", ".HK", ".T", ".AX", ".TO", ".V"]
    return not any(t.endswith(s) for s in FOREIGN)


def detect_sector_usa(ticker: str, yf_sector: str = "") -> str:
    """Detect US sector from ticker symbol and Yahoo Finance sector string."""
    t = ticker.lower().replace("-", "").replace(".", "")

    TICKER_OVERRIDES_USA = {
        "us_mega_tech":           ["aapl","msft","googl","goog","meta","amzn","nvda","nflx"],
        "us_semiconductors":      ["nvda","amd","intc","qcom","txn","avgo","mu","mrvl","on","mpwr","klac","lam","amat","asml"],
        "us_it_services":         ["acn","crm","orcl","intu","adbe","now","ibm","csco","sap",
                                    # Data, analytics & exchanges — asset-light, very high FCF margin
                                    "spgi","mco","msci","ndaq","cboe","ice","cme","br","vrsk",
                                    # Payment networks — technology companies, not banks
                                    "v","ma","pypl","sq","fisv","fis","gfn","gpn"],
        "us_consumer_staples":    ["ko","pep","pg","cl","gis","k","mo","pm","cost","wmt","tgt","kr","sbux"],
        "us_consumer_disc":       ["tsla","nke","mcd","hd","low","f","gm","tjx","ross","bkng","abnb","lyft","uber"],
        "us_pharma":              ["jnj","pfe","mrk","abbv","lly","amgn","bmy","gild","biib","regn","vrtx","zts","mrna"],
        "us_healthcare_services": ["unh","cvs","ci","hum","hca","tmo","abt","dhr","bax","iqv"],
        "us_banks":               ["jpm","bac","wfc","c","gs","ms","schw","blk","axp",
                                    "usb","pnc","cof","aig","met","pru","afl","all","trv","cb","brkb","brka"],
        "us_energy":              ["xom","cvx","cop","eog","slb","hal","bkr","vlo","psx","mpc","hes","dvn","fang"],
        "us_industrials":         ["hon","rtx","lmt","noc","gd","ba","cat","de","ups","fdx","emr","etn","mmm","ge","ir","otis","carr"],
        "us_utilities":           ["nee","duk","so","d","aep","exc","ed","xel","peg","pcg","awk","es","etr"],
        "us_reits":               ["pld","amt","eqix","spg","o","dlr","avb","eqr","are","bxp","vno","cci","sbac"],
        "us_materials":           ["fcx","nem","nue","stld","clf","x","aa","dd","dow","lyb","lin","apd","ecl","ppg"],
        "us_communication":       ["t","vz","cmcsa","dis","nflx","wbd","para","fox","lumn","chtr"],
    }

    for sector_key, keywords in TICKER_OVERRIDES_USA.items():
        if t in keywords:
            return sector_key

    # Yahoo Finance sector fallback
    if yf_sector:
        s = yf_sector.lower()
        if "technology" in s or "software" in s:
            MEGA = {"aapl","msft","googl","goog","meta","amzn","nvda","nflx"}
            if t in MEGA:
                return "us_mega_tech"
            SEMI = {"nvda","amd","intc","qcom","txn","avgo","mu","mrvl"}
            if t in SEMI:
                return "us_semiconductors"
            return "us_it_services"
        if "semiconductor" in s:
            return "us_semiconductors"
        if any(k in s for k in ["consumer staples","food","beverage","household","tobacco"]):
            return "us_consumer_staples"
        if any(k in s for k in ["consumer discretionary","retail","auto","leisure"]):
            return "us_consumer_disc"
        if any(k in s for k in ["healthcare","pharma","biotech","drug"]):
            return "us_healthcare_services" if any(k in s for k in ["service","managed","hospital","diagnostic"]) else "us_pharma"
        if any(k in s for k in ["financ","bank","insurance","asset management"]):
            # Data/analytics companies (SPGI, MCO, MSCI, NDAQ, CME, ICE) are classified
            # as "Financial Services" by Yahoo Finance but are really asset-light IT/data
            DATA_ANALYTICS = {"spgi","mco","msci","ndaq","cboe","ice","cme","br","vrsk"}
            if t in DATA_ANALYTICS:
                return "us_it_services"
            return "us_banks"
        if any(k in s for k in ["energy","oil","gas","petroleum"]):
            return "us_energy"
        if any(k in s for k in ["industrial","aerospace","defence","transport","machinery"]):
            return "us_industrials"
        if any(k in s for k in ["utilities","electric","water"]):
            return "us_utilities"
        if any(k in s for k in ["real estate","reit"]):
            return "us_reits"
        if any(k in s for k in ["materials","chemical","mining","steel","metal"]):
            return "us_materials"
        if any(k in s for k in ["communication","media","telecom"]):
            return "us_communication"

    return "us_general"


def detect_sector(ticker: str, yf_sector: str = "") -> str:
    """Detect sector — routes US tickers to US WACC table, Indian to India table."""
    if _is_us_ticker(ticker):
        return detect_sector_usa(ticker, yf_sector)

    t = ticker.lower().replace(".ns","").replace(".bo","")

    # ── Ticker-first overrides ─────────────────────────────────
    # Yahoo Finance misclassifies many Indian stocks
    # e.g. Asian Paints → "Basic Materials" → metals (WRONG, should be consumer_durable)
    # e.g. Reliance → "Energy" → oil_gas (correct but moat needs scale recognition)
    TICKER_OVERRIDES = {
        "consumer_durable": [
            "asianpaint","berger","kansaineo","akzoindia","pidilitind",
            "havells","voltas","bluestar","whirlpool","vguard","crompton",
            "orient","bajajele","titan","kajariacer","somanycer","cera",
        ],
        "fmcg": [
            "hindunilvr","itc","nestle","britannia","dabur","marico",
            "colpal","godrejcp","emami","jyothy","bajajcon","tataconsum",
            "patanjali","pghh","gillette","vstind","godfryphlp",
        ],
        "airlines": [
            "indigo","interglobe","spicejet","akasaair","airindia","goair",
        ],
        "oil_gas": [
            "reliance","ongc","bpcl","hindpetro","ioc","gail","petronet",
            "atgl","mgl","igl","gspl","gujgasltd","mahangas","coalindia",
        ],
        "realty": [
            "dlf","godrejprop","oberoi","prestige","phoenix","brigade",
            "sobha","mahlife","koltepatil","sunteck",
        ],
        "defence": [
            "hal","bel","beml","cochinship","grse","mazagon","paras",
        ],
        "cement": [
            "ultracemco","ambujacement","shreecem","dalmia","jkcement",
            "ramcocem","heidelberg","birlacorpn","starcement","jswcement",
            "nuvoco","indiacem",
        ],
        "auto_oem": [
            "maruti","tatamotors","bajajauto","heromotoco","tvsmotor",
            "eichermot","ashokley","escorts","royalenf",
        ],
        "metals": [
            "tatasteel","jswsteel","sail","hindalco","vedl","nmdc","jspl",
            "moil","nationalum","hindcopper",
        ],
        "it_services": [
            "tcs","infy","wipro","hcltech","techm","ltim","persistent",
            "coforge","mphasis","ltimindtr","kpittech","tataelxsi",
        ],
        "pharma": [
            "sunpharma","drreddy","cipla","lupin","auropharma","divislab",
            "torntpharm","alkem","biocon","glenmark","natco","mankind",
            "zyduslife","abbotindia","ipca","ipcalab","fdc","granules",
        ],
        "chemicals": [
            "atul","deepakntr","srf","gnfc","coromandel","pi","vinati",
            "navin","clean","tatachem","ghcl","epigral",
        ],
        "capital_goods": [
            "siemens","abb","bhel","thermax","cumminsind","kirloseng",
            "elgiequip","kec","kalpatpowr","powermech","isgec","laxmimach",
        ],
    }
    for sector_key, keywords in TICKER_OVERRIDES.items():
        if any(kw in t for kw in keywords):
            return sector_key

    # Yahoo Finance sector mapping
    if yf_sector:
        s = yf_sector.lower()
        if any(k in s for k in ["technology","software","it service"]):
            return "it_services"
        if any(k in s for k in ["consumer staples","fmcg","food","beverage","household"]):
            return "fmcg"
        if any(k in s for k in ["healthcare","pharma","drug","biotech"]):
            return "hospital" if any(k in s for k in ["hospital","clinic","diagnostic"]) else "pharma"
        if any(k in s for k in ["automobile","auto","vehicle"]):
            return "auto_oem"
        if any(k in s for k in ["energy","oil","gas","petroleum"]):
            return "oil_gas"
        if any(k in s for k in ["utilities","power","electric"]):
            return "power"
        if any(k in s for k in ["materials","metal","mining","steel","aluminium"]):
            return "metals"
        if any(k in s for k in ["cement","construction material"]):
            return "cement"
        if any(k in s for k in ["real estate","realty","property"]):
            return "realty"
        if any(k in s for k in ["telecom","communication"]):
            return "telecom"
        if any(k in s for k in ["retail","consumer discretionary"]):
            return "retail"
        if any(k in s for k in ["chemical","specialty"]):
            return "chemicals"
        if any(k in s for k in ["airline","aviation"]):
            return "airlines"
        if any(k in s for k in ["industrial","capital good","engineering","machinery"]):
            return "capital_goods"
        if any(k in s for k in ["transport","logistics","freight"]):
            return "logistics"
        if any(k in s for k in ["infrastructure","construction"]):
            return "infrastructure"

    # Ticker keyword fallback
    for sector_key, sector_data in INDUSTRY_WACC.items():
        if sector_key == "general":
            continue
        for kw in sector_data.get("keywords", []):
            if kw in t:
                return sector_key

    return "general"


# ══════════════════════════════════════════════════════════════
# CAPEX & WORKING CAPITAL ADJUSTMENT
# ══════════════════════════════════════════════════════════════

def get_sector_fcf_adjustment(
    sector:        str,
    revenue:       float,
    reported_fcf:  float,
    op_income:     float,
) -> dict:
    """
    Apply sector-specific capex and working capital adjustments to FCF.

    Returns
    -------
    dict with:
        adjusted_fcf    : FCF after sector adjustments
        capex_estimate  : estimated normal capex for this sector
        wc_change       : estimated working capital change
        notes           : explanation of adjustments
    """
    sector_data = INDUSTRY_WACC.get(sector, INDUSTRY_WACC["general"])
    tax_rate    = 0.25

    capex_pct  = sector_data["capex_intensity"]
    wc_pct     = sector_data["wc_pct_revenue"]
    fcf_conv   = sector_data["fcf_conv_factor"]
    depr_pct   = sector_data["depreciation_pct"]

    # Normalised capex = sector typical % of revenue
    normal_capex = revenue * capex_pct

    # Working capital change (positive WC change uses cash)
    # We use 10% of the WC balance as annual change estimate
    wc_balance = revenue * abs(wc_pct)
    wc_change  = wc_balance * 0.10 * (1 if wc_pct > 0 else -1)

    # NOPAT-based FCF estimate
    if op_income > 0:
        nopat       = op_income * (1 - tax_rate)
        depr        = revenue * depr_pct
        nopat_fcf   = (nopat + depr - normal_capex - wc_change) * fcf_conv
    else:
        nopat_fcf   = 0

    # If reported FCF is available and positive, blend with NOPAT estimate
    if reported_fcf > 0 and nopat_fcf > 0:
        # Weight: 60% reported (actual), 40% NOPAT (normalised)
        adjusted_fcf = 0.60 * reported_fcf + 0.40 * nopat_fcf
        method = "60% reported + 40% NOPAT-adjusted"
    elif reported_fcf > 0:
        adjusted_fcf = reported_fcf
        method = "reported FCF only"
    elif nopat_fcf > 0:
        adjusted_fcf = nopat_fcf
        method = "NOPAT-adjusted FCF"
    else:
        adjusted_fcf = 0
        method = "no valid FCF"

    return {
        "adjusted_fcf":  adjusted_fcf,
        "capex_estimate": normal_capex,
        "wc_change":      wc_change,
        "nopat_fcf":      nopat_fcf,
        "method":         method,
        "notes": (
            f"Sector capex: {capex_pct:.0%} of rev = {normal_capex/1e9:.1f}B | "
            f"WC change: {wc_change/1e9:.1f}B | "
            f"FCF conv factor: {fcf_conv:.0%}"
        ),
    }


# ══════════════════════════════════════════════════════════════
# MODEL DIAGNOSTICS
# ══════════════════════════════════════════════════════════════

def run_diagnostics(
    sector:         str,
    wacc_used:      float,
    fcf_growth:     float,
    terminal_growth: float,
    tv_pct_of_ev:   float,
    capex_reported: float,
    revenue:        float,
) -> list[dict]:
    """
    Run model diagnostics and return list of warnings.

    Each warning: {"level": "ERROR"|"WARN"|"INFO", "message": str}
    """
    sector_data = INDUSTRY_WACC.get(sector, INDUSTRY_WACC["general"])
    warnings    = []

    # 1. WACC too low for sector
    if wacc_used < sector_data["wacc_min"]:
        warnings.append({
            "level":   "ERROR",
            "message": f"WACC {wacc_used:.1%} below sector minimum {sector_data['wacc_min']:.1%} for {sector}"
        })

    # 2. FCF growth too high
    if fcf_growth > sector_data["fcf_growth_max"]:
        warnings.append({
            "level":   "WARN",
            "message": f"FCF growth {fcf_growth:.1%} exceeds sector max {sector_data['fcf_growth_max']:.1%}"
        })

    # 3. Terminal growth too high
    if terminal_growth > 0.04:
        warnings.append({
            "level":   "ERROR",
            "message": f"Terminal growth {terminal_growth:.1%} exceeds 4% GDP cap"
        })

    # 4. Terminal value concentration
    if tv_pct_of_ev > 0.75:
        warnings.append({
            "level":   "WARN",
            "message": f"Terminal value = {tv_pct_of_ev:.0%} of EV — highly sensitive to growth assumptions"
        })

    # 5. Capex underestimated
    if revenue > 0 and capex_reported > 0:
        reported_pct = capex_reported / revenue
        sector_pct   = sector_data["capex_intensity"]
        if reported_pct < sector_pct * 0.50:
            warnings.append({
                "level":   "WARN",
                "message": f"Reported capex {reported_pct:.1%} of revenue looks low vs sector normal {sector_pct:.1%}"
            })

    # 6. Airlines special check
    if sector == "airlines" and wacc_used < 0.10:
        warnings.append({
            "level":   "ERROR",
            "message": "Airlines WACC must be ≥ 10% — lease liabilities add significant financial risk"
        })

    # 7. High capex sector with low FCF — expected, not a bug
    if sector in ["airlines","infrastructure","power","oil_gas"] and tv_pct_of_ev > 0.80:
        warnings.append({
            "level":   "INFO",
            "message": f"High TV% is typical for {sector} — asset-heavy sectors have high terminal value"
        })

    return warnings


# ══════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ══════════════════════════════════════════════════════════════

def get_industry_wacc(
    ticker:    str,
    yf_sector: str   = "",
    capm_wacc: float = None,
) -> dict:
    """
    Get the appropriate WACC and all sector assumptions for a stock.

    Blends CAPM WACC (40%) with industry default (60%), then applies a
    live risk-free rate adjustment:
      • 10-yr yield > 5%  → +50 bps  (tight financial conditions)
      • 10-yr yield < 3%  → −25 bps  (loose / ZIRP conditions)
      • 3–5%              →   0 bps  (neutral)

    The live yield is fetched from yfinance (^TNX for US, ^INBMK for India)
    and cached for 6 hours via utils.config.fetch_risk_free_rate().

    Returns full sector assumptions including capex, WC, FCF conv,
    and rf_rate_info dict for UI display.
    """
    from utils.config import fetch_risk_free_rate as _fetch_rf

    sector      = detect_sector(ticker, yf_sector)
    sector_data = _ALL_WACC.get(sector, INDUSTRY_WACC["general"])

    wacc_min = sector_data["wacc_min"]
    wacc_max = sector_data["wacc_max"]
    wacc_ind = sector_data["wacc_default"]
    term_g   = sector_data["terminal_growth"]

    # ── Step 1: blend CAPM + industry ──────────────────────────
    if capm_wacc is not None and 0.07 <= capm_wacc <= 0.22:
        blended    = 0.40 * capm_wacc + 0.60 * wacc_ind
        pre_adj    = float(max(wacc_min, min(wacc_max, blended)))
        source     = f"Blended: CAPM {capm_wacc:.1%} (40%) + Industry {wacc_ind:.1%} (60%)"
    else:
        pre_adj    = wacc_ind
        source     = f"Industry default ({sector})"

    # ── Step 2: live RF-rate adjustment ────────────────────────
    _market  = "us" if _is_us_ticker(ticker) else "india"
    _rf_info = _fetch_rf(_market)
    _rf_adj  = _rf_info["wacc_adj"]           # +0.005, -0.0025, or 0.0

    # Apply adjustment; clamp to [wacc_min, wacc_max + 1%] so tight markets
    # can push slightly above the sector ceiling but not into absurd territory
    final_wacc = float(np.clip(pre_adj + _rf_adj, wacc_min, wacc_max + 0.01))

    if _rf_adj != 0.0:
        source += (
            f" + RF adj {_rf_adj:+.2%} "
            f"({_rf_info['rate_pct']:.2f}% {_market.upper()} 10Y, "
            f"{_rf_info['source']})"
        )

    if capm_wacc:
        log.info(
            f"[{ticker}] Sector={sector} | "
            f"Industry WACC={wacc_ind:.1%} | CAPM={capm_wacc:.1%} | "
            f"RF={_rf_info['rate_pct']:.2f}% ({_rf_info['source']}) | "
            f"RF-adj={_rf_adj:+.3%} | Final={final_wacc:.1%} | "
            f"Capex={sector_data['capex_intensity']:.0%}"
        )

    return {
        "wacc":             final_wacc,
        "sector":           sector,
        "sector_name":      sector_data["description"].split("—")[0].strip(),
        "wacc_min":         wacc_min,
        "wacc_max":         wacc_max,
        "terminal_growth":  term_g,
        "beta_typical":     sector_data["beta_typical"],
        "description":      sector_data["description"],
        "notes":            sector_data.get("notes", ""),
        "source":           source,
        # Sector assumptions
        "capex_intensity":  sector_data["capex_intensity"],
        "wc_pct_revenue":   sector_data["wc_pct_revenue"],
        "wc_days":          sector_data["wc_days"],
        "rd_pct_revenue":   sector_data["rd_pct_revenue"],
        "depreciation_pct": sector_data["depreciation_pct"],
        "fcf_conv_factor":  sector_data["fcf_conv_factor"],
        "rev_growth_max":   sector_data["rev_growth_max"],
        "rev_growth_min":   sector_data["rev_growth_min"],
        "fcf_growth_max":   sector_data["fcf_growth_max"],
        # Live rate metadata for UI display
        "rf_rate_info":     _rf_info,
    }
