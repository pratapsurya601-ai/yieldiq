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

# ── Unified bank-like classifier set (2026-04-29) ────────────────
# Single source of truth for "treat this ticker as a bank/NBFC/
# insurance/AMC for valuation + Piotroski + Hex + scoring".
# Mirrors (and extends) the ad-hoc set previously kept inside
# ``screener.piotroski`` so the analysis pipeline, Prism/Hex pipeline
# and Piotroski engine all classify the same tickers identically.
#
# Includes:
#   - core banks (FINANCIAL_COMPANIES already covers majors)
#   - NBFCs / housing finance
#   - life + general insurance
#   - small-finance banks (CAPITALSFB & peers — added after
#     CAPITALSFB.NS surfaced as sector="Chemicals" from yfinance,
#     causing the analysis pipeline to run DCF and produce a
#     headline +289% MoS vs the Prism hex composite of ~5/10).
#   - PSU lender-NBFCs (PFC, RECLTD, IRFC) and AMCs/exchanges
#     that also fail FCF-based DCF.
_NBFC_INSURANCE_BANKLIKE: set[str] = {
    # Banks (majors and tier-2)
    'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK',
    'BANKBARODA', 'PNB', 'CANBK', 'FEDERALBNK', 'IDFCFIRSTB',
    'INDUSINDBK', 'BANDHANBNK', 'RBLBANK', 'YESBANK',
    'IOB', 'UCOBANK', 'CENTRALBK', 'INDIANB', 'MAHABANK',
    'KARURVYSYA', 'CUB', 'DCBBANK', 'SOUTHBANK', 'TMB',
    # Small-Finance Banks (added 2026-04-29 — yfinance frequently
    # mis-tags these with sector="Chemicals" / "Industrials").
    'CAPITALSFB', 'ESAFSFB', 'EQUITASBNK', 'AUBANK',
    'UJJIVANSFB', 'SURYODAY', 'FINOPB', 'JANASURF',
    'UTKARSHBNK', 'FINCABK', 'SFBAJM',
    # NBFCs / housing finance
    'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'MUTHOOTFIN',
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHSGFIN',
    'LICHOUSFIN', 'POONAWALLA', 'AAVAS', 'HOMEFIRST',
    'SBICARD', 'SUNDARMFIN', 'CREDITACC', 'BAJAJHLDNG',
    # PSU lender-NBFCs (regulated utilities of credit)
    'PFC', 'RECLTD', 'IRFC',
    # Insurance
    'HDFCLIFE', 'SBILIFE', 'ICICIPRULI', 'ICICIGI', 'NIACL',
    'STARHEALTH',
}


def is_bank_like(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True if (ticker, sector, industry) describes a bank-
    like business (commercial bank, SFB, NBFC, AMC, insurer).

    Single source of truth shared by the analysis pipeline, Prism /
    Hex, Piotroski and the YieldIQ score path. Three independent
    signals — match on any:

      1. Ticker membership in ``_NBFC_INSURANCE_BANKLIKE`` (extends
         the legacy ``FINANCIAL_COMPANIES`` set; insulates against
         yfinance sector mis-tags such as CAPITALSFB.NS surfacing as
         "Chemicals").
      2. Sector string contains a financial keyword.
      3. Industry string ILIKE 'Bank%' / 'NBFC%' / 'Insurance%' /
         'Asset Management%' / 'Capital Markets%'.
      4. Ticker suffix 'BANK.NS' / 'BANK.BO' / 'FIN.NS' / 'FIN.BO'.

    Returning True routes the ticker to the P/B-multiple valuation
    path (banks have negative FCF by design; FCF-DCF is meaningless)
    and to the bank-mode 4-signal Piotroski.
    """
    if ticker:
        clean = (
            ticker.replace('.NS', '')
            .replace('.BO', '')
            .upper()
        )
        if clean in _NBFC_INSURANCE_BANKLIKE or clean in FINANCIAL_COMPANIES:
            return True
        # Legacy convention: BANK.NS / FIN.NS suffix.
        upper = ticker.upper()
        if upper.endswith(('BANK.NS', 'BANK.BO', 'FIN.NS', 'FIN.BO')):
            return True
    if sector:
        s = sector.strip().lower()
        # Match the broad yfinance "Financial Services" bucket plus
        # the canonical labels we override to in SECTOR_OVERRIDES.
        if s in {
            'banks', 'banking', 'financial services', 'financial',
            'nbfc', 'insurance',
        }:
            return True
        if 'bank' in s or 'nbfc' in s or 'insurance' in s:
            return True
    if industry:
        i = industry.strip().lower()
        for prefix in (
            'bank', 'nbfc', 'insurance',
            'asset management', 'capital markets',
            'financial data', 'credit services',
        ):
            if i.startswith(prefix):
                return True
    return False

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
