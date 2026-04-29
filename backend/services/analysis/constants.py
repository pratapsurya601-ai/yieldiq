# backend/services/analysis/constants.py
# ═══════════════════════════════════════════════════════════════
# Sector classifications, ticker sets, FX rate. Pure data —
# extracted verbatim from the historical analysis_service.py
# monolith. No logic lives here.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations


# ── Company name overrides for cleaner display ──────────────
COMPANY_NAME_OVERRIDES = {
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "Tata Consultancy Services",
    "HDFCBANK.NS": "HDFC Bank",
    "BAJFINANCE.NS": "Bajaj Finance",
    "HINDUNILVR.NS": "Hindustan Unilever",
    "MARUTI.NS": "Maruti Suzuki India",
    "TITAN.NS": "Titan Company",
    "INFY.NS": "Infosys",
    "SBIN.NS": "State Bank of India",
    "ICICIBANK.NS": "ICICI Bank",
    "KOTAKBANK.NS": "Kotak Mahindra Bank",
    "AXISBANK.NS": "Axis Bank",
    "LT.NS": "Larsen & Toubro",
    "SUNPHARMA.NS": "Sun Pharmaceutical Industries",
    "NTPC.NS": "NTPC Limited",
    "ONGC.NS": "ONGC Limited",
    "WIPRO.NS": "Wipro Limited",
    "TATAMOTORS.NS": "Tata Motors",
    "ITC.NS": "ITC Limited",
}

# ── Financial company set (NBFCs, Banks, Insurance) ──────────
# These companies have negative FCF by nature (loan disbursements = operating
# outflows). FCF-based DCF does NOT apply; use P/B ratio valuation instead.
FINANCIAL_COMPANIES = {
    'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK',
    'BANKBARODA', 'PNB', 'CANBK', 'FEDERALBNK', 'IDFCFIRSTB',
    'INDUSINDBK', 'BANDHANBNK', 'RBLBANK', 'YESBANK',
    'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'MUTHOOTFIN',
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHOUSFIN',
    'POONAWALLA', 'AAVAS', 'HOMEFIRST',
    'HDFCLIFE', 'SBILIFE', 'ICICIGI', 'NIACL', 'STARHEALTH',
}

# P/B median multipliers by financial sub-sector
_PB_MEDIANS = {
    "Banking": 2.5,
    "NBFC": 4.0,
    "Insurance": 3.0,
}

_NBFC_TICKERS = {
    'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'MUTHOOTFIN',
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHOUSFIN',
    'POONAWALLA', 'AAVAS', 'HOMEFIRST',
}
_INSURANCE_TICKERS = {
    'HDFCLIFE', 'SBILIFE', 'ICICIGI', 'NIACL', 'STARHEALTH',
}

# Inventory-heavy retail: negative CFO from working capital, not weakness
INVENTORY_HEAVY_TICKERS = {
    'TITAN', 'TRENT', 'ABFRL', 'DMART', 'PAGEIND',
    'RAYMOND', 'VMART', 'MARUTI', 'SHOPERSTOP',
}


# ── Cyclical / commodity tickers ──────────────────────────────
# These businesses have boom-bust earnings and FCF cycles tied to
# commodity prices, capex super-cycles, or global demand. A single
# TTM FCF read at a cycle bottom drives DCF intrinsic value to ~0
# and the verdict logic flips to `data_limited` (see
# service.py:1110-1134). The mitigation: average the last 3 (or 5)
# annual FCF rows so the input reflects mid-cycle economics.
#
# Membership criteria:
#   - Steel / Metals / Mining (cycle-bottom FCF often negative)
#   - Oil & Gas E&P + Integrated (crude price exposure)
#   - Cement / Aluminium (commodity passthrough)
#   - Sugar, Fertilisers (govt-price cyclicality)
#   - Conglomerates with majority-cyclical mix (RELIANCE — O2C)
#
# Conglomerates included on purpose: RELIANCE's O2C segment (~55%
# of consolidated EBITDA) dominates the FCF print, and refining
# margins are textbook cyclical. JIO/Retail are growthier but the
# blended FCF still oscillates with crude.
CYCLICAL_TICKERS: set[str] = {
    # Steel
    'TATASTEEL', 'JSWSTEEL', 'JINDALSTEL', 'SAIL', 'NMDC',
    # Metals & Mining
    'HINDALCO', 'VEDL', 'NATIONALUM', 'HINDZINC', 'HINDCOPPER',
    # Oil & Gas
    'ONGC', 'OIL', 'IOC', 'BPCL', 'HPCL', 'GAIL', 'MGL',
    'IGL', 'PETRONET', 'GUJGASLTD',
    # Cement (cyclical via housing/infra capex)
    'ULTRACEMCO', 'AMBUJACEM', 'ACC', 'SHREECEM', 'DALBHARAT',
    'JKCEMENT', 'RAMCOCEM',
    # Coal
    'COALINDIA',
    # Conglomerates dominated by cyclical segments
    'RELIANCE',
    # Aluminium pure plays already covered above (HINDALCO, VEDL, NATIONALUM)
    # Sugar / Agri-cyclical
    'BALRAMCHIN', 'TRIVENI', 'DHAMPURSUG',
    # Fertilisers (govt subsidy + commodity passthrough)
    'CHAMBLFERT', 'COROMANDEL', 'GSFC', 'RCF', 'GNFC',
    # Shipping (BDI cycle)
    'GESHIP', 'SCI',
}


# Sector-level cyclical detection — used as a fallback when the
# ticker isn't enumerated above but the resolved sector is plainly
# cyclical. Keep the list narrow: false positives here will smooth
# legitimate growth degradation in non-cyclical compounders.
CYCLICAL_SECTORS: set[str] = {
    'Metals & Mining',
    'Oil & Gas',
    'Steel',  # legacy label — survives via SECTOR_OVERRIDES too
}


def is_cyclical(ticker: str | None, sector: str | None = None) -> bool:
    """Return True if the ticker (or its resolved sector) is cyclical.

    Used by the DCF compute path to decide whether to substitute
    a 3-year normalized FCF for the volatile single-year TTM FCF.
    Non-cyclical names continue to use TTM — averaging there would
    mask real degradation.
    """
    if ticker:
        clean = (
            ticker.replace(".NS", "")
            .replace(".BO", "")
            .upper()
        )
        if clean in CYCLICAL_TICKERS:
            return True
    if sector and sector in CYCLICAL_SECTORS:
        return True
    return False


# ── Sector name overrides for cleaner display ─────────────────
SECTOR_OVERRIDES: dict[str, str] = {
    "Financial Services": "Financial Services",
    "Financial": "Financial Services",
    "Banks": "Banking",
    "Banks - Regional": "Banking",
    "Banks - Diversified": "Banking",
    "Insurance - Life": "Insurance",
    "Insurance - Diversified": "Insurance",
    "Insurance": "Insurance",
    "Drug Manufacturers": "Pharma",
    "Drug Manufacturers - General": "Pharma",
    "Biotechnology": "Pharma",
    "Software - Application": "IT",
    "Software - Infrastructure": "IT",
    "Information Technology Services": "IT",
    "Internet Content & Information": "IT",
    "Oil & Gas Integrated": "Oil & Gas",
    "Oil & Gas E&P": "Oil & Gas",
    "Oil & Gas Refining & Marketing": "Oil & Gas",
    "Tobacco": "FMCG",
    "Packaged Foods": "FMCG",
    "Household & Personal Products": "FMCG",
    "Beverages - Non-Alcoholic": "FMCG",
    "Auto Manufacturers": "Automobiles",
    "Auto - Manufacturers": "Automobiles",
    "Telecom Services": "Telecom",
    "Utilities - Regulated Electric": "Power & Utilities",
    "Utilities - Independent Power Producers": "Power & Utilities",
    "Building Materials": "Construction",
    "Engineering & Construction": "Engineering",
    "Specialty Chemicals": "Chemicals",
    "Metals & Mining": "Metals & Mining",
    "Steel": "Metals & Mining",
    "Real Estate - Development": "Real Estate",
    "REIT": "Real Estate",
}


# Ticker-based sector overrides — forces correct sector for known tickers
# (yfinance often returns "Financial Services" for everything)
TICKER_SECTOR_OVERRIDES: dict[str, str] = {}
for _t in _NBFC_TICKERS:
    TICKER_SECTOR_OVERRIDES[_t] = "NBFC"
for _t in _INSURANCE_TICKERS:
    TICKER_SECTOR_OVERRIDES[_t] = "Insurance"
for _t in (FINANCIAL_COMPANIES - _NBFC_TICKERS - _INSURANCE_TICKERS):
    TICKER_SECTOR_OVERRIDES[_t] = "Banking"


# USD → INR conversion rate for Financials rows tagged `currency = 'USD'`.
# TODO: source from a forex feed (RBI reference rate) rather than a constant.
USD_INR_RATE = 83.5
