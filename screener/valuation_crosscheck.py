# ═══════════════════════════════════════════════════════════════
# HONEST ASSESSMENT & FIXES
# ═══════════════════════════════════════════════════════════════
#
# WHY HUL/SUNPHARMA/MARUTI show very low DCF value:
#
# DCF gives HUL IV = ₹760 vs CMP ₹2175
# This is NOT necessarily wrong — it reflects that:
#
# 1. HUL FCF = ~₹8000 Cr
#    Shares = 235 Cr
#    FCF/share = ₹34
#    At WACC 10%, Terminal g 4%:
#    TV multiple = (1+0.04)/(0.10-0.04) = 17.3x
#    Even at 17.3x terminal multiple, IV is low
#    BUT MARKET PRICES HUL AT 65x PE — that's the premium!
#
# 2. SUNPHARMA trades at 45x PE because of:
#    - Patent-protected drugs
#    - US generics pipeline
#    - Brand value
#    DCF can't capture these intangibles
#
# 3. MARUTI trades at 28x PE because:
#    - Market leader in India (largest auto market)
#    - Future EV optionality
#    - Strong balance sheet
#
# THE RIGHT APPROACH:
# Add a PE-cross check alongside DCF.
# If PE-based value > DCF value for premium sectors → use blend
# ═══════════════════════════════════════════════════════════════
#
# FILE: screener/valuation_crosscheck.py
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)

# ── Sector PE multiples (India market, March 2026) ─────────────
# Based on historical median PE for quality large-caps in each sector
SECTOR_PE = {
    # ── Indian sectors ─────────────────────────────────────────────
    "fmcg":           {"pe_median": 48, "pe_bear": 35, "pe_bull": 65},
    "pharma":         {"pe_median": 32, "pe_bear": 22, "pe_bull": 48},
    "hospital":       {"pe_median": 40, "pe_bear": 28, "pe_bull": 58},
    "it_services":    {"pe_median": 24, "pe_bear": 18, "pe_bull": 30},
    "tech_hardware":  {"pe_median": 30, "pe_bear": 22, "pe_bull": 40},
    "auto_oem":       {"pe_median": 25, "pe_bear": 18, "pe_bull": 35},
    "auto_ancillary": {"pe_median": 22, "pe_bear": 16, "pe_bull": 30},
    "capital_goods":  {"pe_median": 35, "pe_bear": 25, "pe_bull": 50},
    "defence":        {"pe_median": 45, "pe_bear": 32, "pe_bull": 65},
    "oil_gas":        {"pe_median": 18, "pe_bear": 10, "pe_bull": 28},
    "power":          {"pe_median": 18, "pe_bear": 12, "pe_bull": 25},
    "metals":         {"pe_median": 10, "pe_bear": 6,  "pe_bull": 16},
    "cement":         {"pe_median": 20, "pe_bear": 15, "pe_bull": 28},
    "realty":         {"pe_median": 25, "pe_bear": 15, "pe_bull": 40},
    "telecom":        {"pe_median": 35, "pe_bear": 20, "pe_bull": 55},
    "retail":         {"pe_median": 55, "pe_bear": 35, "pe_bull": 80},
    "media":          {"pe_median": 20, "pe_bear": 12, "pe_bull": 32},
    "logistics":      {"pe_median": 30, "pe_bear": 20, "pe_bull": 45},
    "chemicals":      {"pe_median": 28, "pe_bear": 18, "pe_bull": 40},
    "consumer_durable":{"pe_median": 40, "pe_bear": 28, "pe_bull": 55},
    # ── US sectors — Damodaran S&P median PE multiples ─────────────
    "us_mega_tech":           {"pe_median": 28, "pe_bear": 20, "pe_bull": 38},
    "us_semiconductors":      {"pe_median": 25, "pe_bear": 16, "pe_bull": 35},
    "us_it_services":         {"pe_median": 22, "pe_bear": 15, "pe_bull": 30},
    "us_pharma":              {"pe_median": 18, "pe_bear": 12, "pe_bull": 25},
    "us_healthcare_services": {"pe_median": 18, "pe_bear": 13, "pe_bull": 25},
    "us_banks":               {"pe_median": 12, "pe_bear":  8, "pe_bull": 16},
    "us_energy":              {"pe_median": 12, "pe_bear":  7, "pe_bull": 18},
    "us_industrials":         {"pe_median": 20, "pe_bear": 14, "pe_bull": 28},
    "us_utilities":           {"pe_median": 16, "pe_bear": 12, "pe_bull": 22},
    "us_consumer_staples":    {"pe_median": 20, "pe_bear": 15, "pe_bull": 27},
    "us_consumer_disc":       {"pe_median": 22, "pe_bear": 14, "pe_bull": 32},
    "us_reits":               {"pe_median": 35, "pe_bear": 22, "pe_bull": 48},   # P/FFO not P/E
    "us_materials":           {"pe_median": 15, "pe_bear":  9, "pe_bull": 22},
    "us_communication":       {"pe_median": 14, "pe_bear":  9, "pe_bull": 20},
    "us_general":             {"pe_median": 20, "pe_bear": 14, "pe_bull": 28},
    # ── Fallback ───────────────────────────────────────────────────
    "general":        {"pe_median": 22, "pe_bear": 15, "pe_bull": 30},
}

# How much weight to give PE vs DCF per sector
# FMCG, pharma → market PE is more reliable than DCF
# Metals, oil → DCF is more reliable
SECTOR_PE_WEIGHT = {
    # ── Indian sectors ─────────────────────────────────────────────
    "fmcg":           0.45,
    "pharma":         0.55,
    "hospital":       0.55,
    "it_services":    0.35,
    "saas_software":  0.55,
    "tech_hardware":  0.40,
    "auto_oem":       0.40,
    "auto_ancillary": 0.35,
    "capital_goods":  0.40,
    "defence":        0.50,
    "oil_gas":        0.55,
    "power":          0.35,
    "metals":         0.25,
    "cement":         0.35,
    "realty":         0.35,
    "telecom":        0.45,
    "retail":         0.55,
    "media":          0.40,
    "logistics":      0.40,
    "chemicals":      0.35,
    "consumer_durable":0.50,
    "airlines":       0.45,
    "infrastructure": 0.40,
    # ── US sectors — DCF is primary for most, PE is crosscheck ──────
    # Payment processors / data cos: DCF more reliable (cash EPS misleads)
    "us_mega_tech":           0.35,   # 65% DCF — strong FCF, DCF reliable
    "us_semiconductors":      0.30,   # 70% DCF — cyclical, DCF better
    "us_it_services":         0.30,   # 70% DCF — acquisition-heavy, adj EPS misleads
    "us_pharma":              0.50,   # 50/50 — pipeline optionality in PE
    "us_healthcare_services": 0.40,
    "us_banks":               0.55,   # banks: book value + PE more reliable than DCF
    "us_energy":              0.45,
    "us_industrials":         0.35,
    "us_utilities":           0.40,
    "us_consumer_staples":    0.45,
    "us_consumer_disc":       0.40,
    "us_reits":               0.30,   # REITs: use FFO, DCF more reliable
    "us_materials":           0.30,
    "us_communication":       0.40,
    "us_general":             0.35,
    # ── Fallback ──────────────────────────────────────────────────
    "general":        0.40,
}


def compute_pe_based_iv(
    eps:        float,
    sector:     str,
    scenario:   str = "base",
    growth:     float = None,   # pass revenue growth to adjust PE for declining cos
) -> float:
    """
    Compute intrinsic value using sector PE multiple.
    IV = EPS × Sector_PE_multiple
    PE is adjusted downward for companies with declining/negative growth.
    """
    if eps <= 0:
        return 0.0

    sector_data = SECTOR_PE.get(sector, SECTOR_PE["general"])

    if scenario == "bear":
        pe = sector_data["pe_bear"]
    elif scenario == "bull":
        pe = sector_data["pe_bull"]
    else:
        pe = sector_data["pe_median"]

    # IB fix: declining businesses get a PE haircut
    # A company with -15% revenue growth should not get 45x PE
    # Apply graduated discount based on growth rate
    if growth is not None:
        if growth < -0.10:
            pe = pe * 0.40   # severe decline: 60% PE haircut (patent cliff, disruption)
        elif growth < -0.05:
            pe = pe * 0.55   # meaningful decline: 45% haircut
        elif growth < 0:
            pe = pe * 0.70   # mild decline: 30% haircut
        elif growth < 0.03:
            pe = pe * 0.85   # very low growth: 15% haircut

    return eps * pe


def blend_dcf_pe(
    dcf_iv:   float,
    pe_iv:    float,
    sector:   str,
) -> float:
    """
    Blend DCF and PE-based intrinsic values.

    For premium sectors (FMCG, pharma), PE gets more weight.
    For commodity sectors (metals, oil), DCF gets more weight.
    """
    if pe_iv <= 0:
        return dcf_iv
    if dcf_iv <= 0:
        return pe_iv

    pe_weight  = SECTOR_PE_WEIGHT.get(sector, 0.35)
    dcf_weight = 1 - pe_weight

    blended = pe_weight * pe_iv + dcf_weight * dcf_iv

    log.debug(
        f"IV blend: DCF={dcf_iv:.0f} ({dcf_weight:.0%}) + "
        f"PE={pe_iv:.0f} ({pe_weight:.0%}) = {blended:.0f}"
    )
    return blended


def get_eps(enriched: dict) -> float:
    """
    Get best EPS for PE valuation.
    Priority: forward EPS (FY+1 Yahoo) > trailing EPS > net income/shares
    IB standard: always use forward EPS for target prices.
    """
    shares     = enriched.get("shares",         0)
    price      = enriched.get("price",          0)
    latest_rev = enriched.get("latest_revenue", 0)
    ticker     = enriched.get("ticker",         "?")
    sector     = enriched.get("sector",         "general")
    income_df  = enriched.get("income_df",      None)

    if shares <= 0:
        return 0.0

    # ── Priority 1: Forward EPS from Yahoo (FY+1 analyst estimate) ─
    forward_eps = enriched.get("forward_eps", 0)
    if forward_eps > 0:
        fwd_pe = price / forward_eps if forward_eps > 0 else 0
        # Tightened: fwd_pe must be 8-100x for non-financials
        # <8x usually means Yahoo is using adjusted/cash EPS (strips goodwill amort.)
        # which can massively inflate PE-based IV for acquisition-heavy companies
        # (GPN, FISV, FIS etc have cash EPS 4-5x their GAAP EPS)
        _is_financial = enriched.get("sector","") in {"us_banks","us_reits"}
        _pe_floor = 5 if _is_financial else 8
        if _pe_floor <= fwd_pe <= 100:
            log.debug(f"[{ticker}] Using forward EPS ₹{forward_eps:.1f} (fwd P/E={fwd_pe:.0f}x)")
            return forward_eps

    # ── Priority 2: Trailing EPS from Yahoo ────────────────────────
    trailing_eps = enriched.get("trailing_eps", 0)
    if trailing_eps > 0:
        trail_pe = price / trailing_eps if trailing_eps > 0 else 0
        _is_financial = enriched.get("sector","") in {"us_banks","us_reits"}
        _pe_floor = 5 if _is_financial else 8
        if _pe_floor <= trail_pe <= 150:
            log.debug(f"[{ticker}] Using trailing EPS ₹{trailing_eps:.1f} (P/E={trail_pe:.0f}x)")
            return trailing_eps

    # ── Priority 3: Compute from income statement ───────────────────
    SECTOR_MAX_MARGIN = {
        "pharma":          0.35,
        "it_services":     0.30,
        "fmcg":            0.28,
        "consumer_durable":0.22,
        "hospital":        0.18,
        "chemicals":       0.22,
        "general":         0.28,
    }
    max_margin    = SECTOR_MAX_MARGIN.get(sector, 0.28)
    rev_per_share = latest_rev / shares if shares > 0 else 0
    eps_rev_cap   = rev_per_share * max_margin
    eps_price_cap = price / 3 if price > 0 else float("inf")

    raw_eps = 0.0
    if income_df is not None and not income_df.empty and "net_income" in income_df.columns:
        net_income = float(income_df["net_income"].iloc[-1])
        if net_income > 0:
            raw_eps = net_income / shares

    if raw_eps <= 0:
        fcf = enriched.get("latest_fcf", 0)
        if fcf > 0:
            raw_eps = fcf / shares

    if raw_eps <= 0:
        return 0.0

    if eps_rev_cap > 0 and raw_eps > eps_rev_cap:
        log.warning(f"[{ticker}] EPS {raw_eps:.2f} > cap {eps_rev_cap:.2f} — suppressing PE IV")
        return 0.0

    if raw_eps > eps_price_cap:
        log.warning(f"[{ticker}] EPS {raw_eps:.2f} > price/3 cap — suppressing PE IV")
        return 0.0

    return raw_eps
