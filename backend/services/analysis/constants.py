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
    # Top-tier private banks
    'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK',
    # PSU banks (expanded 2026-05-19 — see PR #385 fix)
    'BANKBARODA', 'PNB', 'CANBK', 'FEDERALBNK', 'IDFCFIRSTB',
    'INDUSINDBK', 'BANDHANBNK', 'RBLBANK', 'YESBANK',
    'BANKINDIA', 'IOB', 'CENTRALBK', 'UCOBANK', 'MAHABANK',
    'IDBI', 'UNIONBANK', 'INDIANB',
    # NBFCs / housing finance
    'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'MUTHOOTFIN',
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHSGFIN',
    'POONAWALLA', 'AAVAS', 'HOMEFIRST',
    # Insurance (life + general + health)
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
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHSGFIN',
    'POONAWALLA', 'AAVAS', 'HOMEFIRST',
}
_INSURANCE_TICKERS = {
    # Life insurers (Appraisal Value engine consumers — see
    # docs/design/insurance-dcf-fix.md and backend/services/
    # insurance_appraisal_service.py). ICICIPRULI / LICI were added
    # 2026-05-18 alongside the EV/VNB admin entry workflow so the
    # admin endpoint validator accepts them.
    'HDFCLIFE', 'SBILIFE', 'ICICIPRULI', 'LICI',
    # General + health insurers (NOT routed through Appraisal Value;
    # P/BV cohort with combined-ratio overlay — out of scope here).
    # 2026-05-19 expansion: GICRE/GODIGIT/NIVABUPA added to keep the
    # insurance classifier consistent with the new psu_gi / private_gi
    # / health_insurance peer buckets in financial_valuation_service.
    'ICICIGI', 'NIACL', 'GICRE', 'GODIGIT',
    'STARHEALTH', 'NIVABUPA',
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
    # Banks (majors and tier-2). PSU expansion 2026-05-19:
    # BANKINDIA + IDBI + UNIONBANK added (were silently missing
    # despite being major listed PSU banks).
    'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK',
    'BANKBARODA', 'PNB', 'CANBK', 'FEDERALBNK', 'IDFCFIRSTB',
    'INDUSINDBK', 'BANDHANBNK', 'RBLBANK', 'YESBANK',
    'BANKINDIA', 'IOB', 'UCOBANK', 'CENTRALBK', 'INDIANB',
    'MAHABANK', 'IDBI', 'UNIONBANK',
    'KARURVYSYA', 'CUB', 'DCBBANK', 'SOUTHBANK', 'TMB',
    # Small-Finance Banks (added 2026-04-29 — yfinance frequently
    # mis-tags these with sector="Chemicals" / "Industrials").
    'CAPITALSFB', 'ESAFSFB', 'EQUITASBNK', 'AUBANK',
    'UJJIVANSFB', 'SURYODAY', 'FINOPB', 'JANASURF',
    'UTKARSHBNK', 'FINCABK', 'SFBAJM',
    # NBFCs / housing finance
    'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'MUTHOOTFIN',
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHSGFIN',
    'PNBHOUSING', 'CANFINHOME',
    'POONAWALLA', 'AAVAS', 'HOMEFIRST',
    'SBICARD', 'SUNDARMFIN', 'CREDITACC', 'BAJAJHLDNG',
    # PSU lender-NBFCs (regulated utilities of credit)
    'PFC', 'RECLTD', 'IRFC',
    # Insurance — life + general + health + reinsurance
    # 2026-05-19 expansion: GICRE/GODIGIT/NIVABUPA/LICI added.
    # Without these, is_bank_like() returned False and the financial-
    # services valuation path was bypassed → GICRE's PR #383 psu_gi
    # peer bucket was dead code (FV +103% over consensus post-deploy).
    'HDFCLIFE', 'SBILIFE', 'ICICIPRULI', 'LICI',
    'ICICIGI', 'NIACL', 'GICRE', 'GODIGIT',
    'STARHEALTH', 'NIVABUPA',
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

# Inventory-heavy retail: negative CFO from working capital, not weakness.
# Extended 2026-04-29 (PR working-capital-adjusted FCF): added jewellery
# (KALYANKJIL, RAJESHEXPO, MUTHOOTGOLD, TBZ, PCJEWELLER, TRIBHOVANDAS),
# beverages (VBL/VARUNBEV) and heavy-equipment dealerships (ESCORTS,
# TIINDIA) which all show volatile WC swings during expansion cycles.
INVENTORY_HEAVY_TICKERS = {
    # Jewellery
    'TITAN', 'KALYANKJIL', 'RAJESHEXPO', 'MUTHOOTGOLD', 'TBZ',
    'PCJEWELLER', 'TRIBHOVANDAS',
    # Retail (apparel + general merchandise)
    'DMART', 'TRENT', 'ABFRL', 'VMART', 'SHOPERSTOP', 'VENKEYS',
    'LIBERTSHOE', 'BATAINDIA', 'PAGEIND', 'RAYMOND',
    # Beverages / consumer cyclic
    'VBL', 'VARUNBEV',
    # Heavy-equipment dealerships (high WC)
    'ESCORTS', 'TIINDIA',
    # Auto OEM with large dealer-network inventory
    'MARUTI',
}


_INVENTORY_HEAVY_SECTORS = {"Retail", "Apparel"}
_INVENTORY_HEAVY_INDUSTRY_KEYWORDS = (
    "jewellery", "jewelry", "retail trade", "department stores",
    "gems", "diamond",
)


def is_inventory_heavy(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True for inventory-heavy businesses where reported FCF
    swings wildly year-to-year as inventory builds/depletes during
    expansion (jewellery, retail, beverages, gem/diamond).

    For these tickers the DCF should smooth working-capital deltas over
    a 3y window when computing the FCF base — see
    ``models/forecaster._compute_fcf_base``.

    Three independent signals — match on any:
      1. Ticker membership in :data:`INVENTORY_HEAVY_TICKERS`.
      2. Industry string contains a known inventory-heavy keyword
         (jewellery, retail trade, gems, diamond, ...).
      3. Sector string equals one of the curated inventory-heavy sector
         labels ("Retail", "Apparel").
    """
    bare = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
    if bare and bare in INVENTORY_HEAVY_TICKERS:
        return True
    i = (industry or "").lower()
    if i and any(k in i for k in _INVENTORY_HEAVY_INDUSTRY_KEYWORDS):
        return True
    s = (sector or "").strip()
    if s and any(s.lower() == k.lower() for k in _INVENTORY_HEAVY_SECTORS):
        return True
    return False


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


# ─────────────────────────────────────────────────────────────────────
# Capex super-cyclical classifier (added 2026-04-30, PR A)
#
# These tickers/sectors have multi-year capex super-cycles where pure
# 5y "positive FCF only" filters in forecaster.py:_compute_fcf_base
# exclude every realistic data point. The right answer is a SIGNED
# median over a 10y window (negative years included) for the cyclical
# normalisation candidate.
#
# GRASIM is the strongest case (holdco: cement + viscose + paints, all
# capex-heavy; multi-year negative FCF). HINDALCO/VEDL/NALCO are
# aluminium (super-capex). TATASTEEL/JSWSTEEL/JINDALSTEL/SAIL are
# integrated steel (super-cyclic capex).
#
# Cement is INTENTIONALLY EXCLUDED — was removed from _CYCLICAL_SECTORS
# on 2026-04-24 (hotfix/cement-cyclical-cap) because the 5y window
# crushed SHREECEM/ULTRACEMCO during India's current infrastructure
# super-cycle. Cement stays on the normal path.
# ─────────────────────────────────────────────────────────────────────

_CAPEX_SUPER_CYCLICAL_TICKERS: set[str] = {
    # Aluminium / non-ferrous metals
    "HINDALCO", "VEDL", "NALCO",
    # Integrated steel
    "TATASTEEL", "JSWSTEEL", "JINDALSTEL", "SAIL",
    # Diversified holdco with multi-segment super-capex
    "GRASIM",
}


# Window length (years) for the super-cyclical signed-median FCF
# anchor in models/forecaster.py:_compute_fcf_base. Extended from
# 10 → 15 on 2026-05-03 because a 10y look in 2026 sits entirely
# inside India's 2015-2024 metals/cement/auto upcycle and over-
# anchors the "mid-cycle" median ABOVE true mid-cycle, producing
# bear/base FVs that under-shoot the trough-to-peak spread. 15y
# pulls in 2010-2014 (thinner FCF) so the median is honestly
# mid-cycle. Cement is NOT routed here (see comment block above
# _CAPEX_SUPER_CYCLICAL_TICKERS) — cement keeps the normal 5y
# positive-only path per the 2026-04-24 hotfix.
SUPER_CYCLICAL_WINDOW_YEARS: int = 15


# Wide-moat compounders that the sector-keyword fallback in
# is_capex_super_cyclical() would otherwise wrongly bucket as
# super-cyclical (TITAN got flagged via signed-median FCF on a 10y
# window, crushing FV to ~₹1,079 vs current price ~₹3,200). These
# are explicit "never treat as super-cyclical" overrides.
NEVER_SUPER_CYCLICAL: set[str] = {
    "TITAN",        # wide-moat consumer durables (jewellery + watches)
    "ASIANPAINT",   # paints, distribution moat
    "NESTLEIND",    # FMCG
    "HINDUNILVR",   # FMCG
    "BRITANNIA",    # FMCG
    "TATACONSUM",   # FMCG
}


def is_capex_super_cyclical(
    ticker: str,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True if the ticker has a multi-year capex super-cycle
    that breaks the 5y-positive-FCF-only normalisation.

    Decision = (curated ticker allow-list) OR (sector keyword match),
    with NEVER_SUPER_CYCLICAL acting as an early-exit veto for
    wide-moat compounders the keyword fallback would otherwise
    misclassify.
    Cement is NOT in this set (see comment above).
    """
    bare = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
    # Veto: wide-moat compounders never go down the super-cyclical
    # path even if a future sector-keyword match triggers.
    if bare in NEVER_SUPER_CYCLICAL:
        return False
    if bare in _CAPEX_SUPER_CYCLICAL_TICKERS:
        return True
    s = (sector or "").lower()
    i = (industry or "").lower()
    blob = s + " " + i
    if any(token in blob for token in (
        "aluminium", "non-ferrous", "diversified metal",
    )):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────
# Shares-outstanding overrides (added 2026-04-30 P1 launch-aftermath)
#
# yfinance's `sharesOutstanding` field can be stale or wrong after
# corporate actions (mergers, demergers, large QIPs). When it is, the
# entire DCF equity-value-per-share calculation is off by the same
# multiple, giving us garbage FV (POWERINDIA: yfinance returns
# 44.57M which is the pre-Hitachi-acquisition free float; the actual
# post-merger count is ~423M). Override here, before the value flows
# into local_data_service.py / compute_metrics / DCFEngine.
#
# Keys are clean tickers (no .NS/.BO). Values are RAW share counts
# (not lakhs). Applied in local_data_service.py right after
# `shares_raw` is computed from the lakh-stored DB value.
# ─────────────────────────────────────────────────────────────────────
SHARES_OUTSTANDING_OVERRIDES: dict[str, float] = {
    # Hitachi Energy India (post-Hitachi acquisition: yfinance returns
    # the old free-float ~44.57M, actual ~423M shares).
    "POWERINDIA": 423_000_000.0,
}


# ─────────────────────────────────────────────────────────────────────
# Top private banks — bank COE adjustment (added 2026-04-30 P1)
#
# Mature, deposit-franchise-led private banks have lower cost of
# equity than the generic 12.5% the CAPM path lands at for India
# (Re ≈ rf + β·MRP ≈ 7% + 1.0·6% = 13%, floored to 12% under the NBFC
# floor for some). Industry standard for top private banks is
# 10.5–11.5%. Lowering COE has two effects in our pipeline:
#
#   1. Surface `wacc` field reads ≤11% (matches sell-side reports).
#   2. In the P/BV justified-multiple path
#      (financial_valuation_service._compute_pbv_path), fair_pb is
#      bumped by a COE-implied factor: lower COE → higher justified
#      P/BV via Gordon (P/B = (ROE-g)/(COE-g)).
#
# PSU banks (SBIN, BANKBARODA, PNB, etc.) deliberately stay on the
# higher 12.5% path — higher governance/asset-quality risk.
# ─────────────────────────────────────────────────────────────────────
TOP_PRIVATE_BANKS: set[str] = {
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK",
}

# Target COE for top private banks (mid-point of the 10.5-11.5% band).
TOP_PRIVATE_BANK_COE = 0.11

# Bump factor applied to peer-median P/BV for top private banks.
# Calibrated so HDFCBANK (current P/BV ≈ 2.7, peer-median ≈ 2.4)
# moves FV from ~₹676 toward ~₹780, closing the spurious -12% MoS
# gap surfaced on Reddit. Equivalent to a ~150bps COE compression.
TOP_PRIVATE_BANK_PB_BUMP = 1.15


def is_top_private_bank(ticker: str | None) -> bool:
    """Return True if the ticker is in the curated top-private-banks
    set (HDFCBANK / ICICIBANK / KOTAKBANK / AXISBANK).
    """
    if not ticker:
        return False
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    return bare in TOP_PRIVATE_BANKS


# ─────────────────────────────────────────────────────────────────────
# Regulated-utility classifier (added 2026-05-18, PR
# feat/regulated-utility-dcf-engine)
#
# Mirrors REGULATED_UTILITY_TICKERS in models/industry_wacc.py. Used by
# backend/services/analysis/service.py to route these tickers through
# the rate-base valuation path (regulated_utility_valuation_service)
# instead of generic FCF-DCF, which structurally mis-values CERC /
# PNGRB-regulated cash flows (debt double-penalty + capex-erodes-FCF).
# Single import in service.py keeps the wiring readable.
# ─────────────────────────────────────────────────────────────────────


def is_regulated_utility(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True if `ticker` should be valued via the rate-base
    regulated-utility engine (CERC / PNGRB / state tariff orders).

    Ticker membership in :data:`models.industry_wacc.REGULATED_UTILITY_TICKERS`
    is the single source of truth. `sector` / `industry` arguments are
    accepted (and currently ignored) so the call site has the same shape
    as ``is_bank_like`` / ``is_cyclical`` and so we can extend to keyword
    fallbacks without churning every caller.
    """
    if not ticker:
        return False
    try:
        from models.industry_wacc import REGULATED_UTILITY_TICKERS
    except Exception:
        return False
    bare = (
        ticker.replace(".NS", "")
        .replace(".BO", "")
        .upper()
    )
    return bare in REGULATED_UTILITY_TICKERS


# ─────────────────────────────────────────────────────────────────────
# ETF / exchange-traded-fund classifier (added 2026-05-18, audit step 2,
# PR feat/etf-asset-type-classifier)
#
# ETFs are NOT operating businesses. They hold a basket of underlying
# securities and their fair value is the iNAV / NAV of those holdings
# published by the issuer daily — NOT a DCF on the fund's own "cash
# flows" (there are none in the operating-business sense). Running the
# generic FCF-DCF path on an ETF ticker produces structurally nonsense
# FVs (typically near-zero because the trust has no FCF to project).
#
# Detection = (curated ticker allow-list) OR (ticker keyword fallback)
# OR (sector/industry/quoteType signal). Curated set is the primary
# defence; keyword fallback ("ETF", "BEES", "NIF50", "GILT", "GOLDETF"
# in the ticker) catches the long tail of AMC-branded ETFs we haven't
# enumerated. quoteType=='ETF' from yfinance is the third signal.
#
# Routed via service.py BEFORE is_regulated_utility_ticker — ETF wins
# over every other classifier (an ETF that happens to hold utility
# stocks must still be valued as an ETF, not as a utility).
# ─────────────────────────────────────────────────────────────────────

ETF_TICKERS: set[str] = {
    # Nippon India / BeES family
    "NIFTYBEES", "BANKBEES", "LIQUIDBEES", "GOLDBEES", "SILVERBEES",
    "JUNIORBEES", "ITBEES", "PSUBNKBEES", "INFRABEES", "CONSUMBEES",
    "DIVOPPBEES", "SHARIABEES",
    # ICICI Prudential
    "ICICIB22", "ICICILIQ", "ICICINIFTY", "ICICITECH",
    # Motilal Oswal
    "MOM100", "MOM50", "MOSt100", "MAFANG", "MASPTOP50", "MAFSETFIT",
    # SBI Mutual Fund
    "SETFNIF50", "SBIETFNIF", "SBIETFGOLD", "SBIETFCON", "SETFNN50",
    "SBIETFPB", "SBIETFQLTY",
    # Kotak
    "KOTAKBKETF", "KOTAKLIQUID", "KOTAKNIFTY", "KOTAKPSUBK", "KOTAKNV20",
    "KOTAKGOLD", "KOTAKIT",
    # HDFC
    "HDFCNIFETF", "HDFCSENSEX", "HDFCNIFBAN", "HDFCMID150", "HDFCSML250",
    # Axis
    "AXISNIFTY", "AXISBNKETF", "AXISGOLD", "AXISTECETF",
    # Aditya Birla Sun Life / Mirae / IDFC / Edelweiss / others
    "ABSLNN50ET", "BSLNIFTY", "MIRAEMETF", "IDFNIFTYET",
    "NIFTYIETF", "NETFNIF50", "NETFNIFBK",
    # Edelweiss / DSP / Quantum etc
    "EDELWEISS", "DSPNIFTY", "QGOLDHALF", "GOLDSHARE",
}


_ETF_KEYWORD_PATTERNS = (
    "ETF",
    "BEES",
    "NIF50",
    "GILT",
    "GOLDETF",
    "SILVERETF",
    "LIQUIDCASE",
)


def is_etf(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
    security_type: str | None = None,
) -> bool:
    """Return True if `ticker` is an Exchange-Traded Fund (ETF).

    Three independent signals — match on any:

      1. Ticker membership in :data:`ETF_TICKERS` (curated allow-list).
      2. Ticker keyword fallback: bare symbol contains one of
         ``ETF``, ``BEES``, ``NIF50``, ``GILT``, ``GOLDETF`` (catches
         the long tail of AMC-branded ETFs not in the curated set).
      3. Upstream metadata says ETF: ``security_type`` (yfinance
         ``quoteType``) equals ``"ETF"``, OR sector/industry text
         contains "exchange-traded fund" / "exchange traded fund".

    ETFs are valued by NAV / iNAV of their underlying holdings — not
    by DCF, P/B, or any operating-business model. service.py
    short-circuits to verdict="data_limited" with
    valuation_method="etf_nav_based" when this returns True.
    """
    if security_type and security_type.strip().upper() == "ETF":
        return True

    if ticker:
        bare = (
            ticker.replace(".NS", "")
            .replace(".BO", "")
            .upper()
        )
        if bare in ETF_TICKERS:
            return True
        # Keyword fallback — anchored on the bare (no-suffix) symbol so
        # we don't false-positive on company names that incidentally
        # contain these substrings via the .NS / .BO suffix.
        for kw in _ETF_KEYWORD_PATTERNS:
            if kw in bare:
                return True

    blob = " ".join(
        (sector or "").lower().strip().split() +
        (industry or "").lower().strip().split()
    )
    if blob:
        if "exchange-traded fund" in blob or "exchange traded fund" in blob:
            return True

    return False


# ─────────────────────────────────────────────────────────────────────
# Defense PSU classifier (added 2026-05-18, PR
# feat/defense-psu-analyst-opinion-flag)
#
# Per docs/design/defense-psu-dcf-fix.md (Approach D — NO-FIX). Indian
# defense PSUs are mid-structural-re-rating (Make-in-India order-book
# surge). Trailing-financials DCF systematically lags forward earning
# power because the multi-year order books signed 2023-2024 are
# invisible to FCF until 2026-2030 deliveries. Street has abandoned
# DCF for the sector and switched to EV/EBITDA on FY27-28E plus
# order-book-to-bill multiples.
#
# We do NOT change WACC / terminal_g / FCF base / sector multiples.
# Instead we:
#   - emit ``analyst_opinion_required: True`` on ValuationOutput
#   - append an explanatory caveat to ``data_issues``
#   - downgrade ``confidence_score *= 0.7`` (forces low-confidence
#     UI badge)
#
# Cache layout is UNCHANGED — purely additive wire-format fields. No
# CACHE_VERSION bump required; cached payloads pick up the new fields
# on next recompute.
# ─────────────────────────────────────────────────────────────────────

DEFENSE_PSU_TICKERS: set[str] = {
    # Listed defense PSUs (govt-owned)
    "HAL",            # Hindustan Aeronautics
    "BEL",            # Bharat Electronics
    "BDL",            # Bharat Dynamics
    "MAZAGON",        # Mazagon Dock Shipbuilders
    "GRSE",           # Garden Reach Shipbuilders & Engineers
    "BEML",           # BEML Limited
    "COCHINSHIP",     # Cochin Shipyard
    "MIDHANI",        # Mishra Dhatu Nigam
    # Private defense (small/illiquid but same analyst-dispersion regime)
    "SOLARINDS",      # Solar Industries India
    "IDEAFORGE",      # ideaForge Technology
    "ZENTEC",         # Zen Technologies
    "ASTRA-MICRO",    # Astra Microwave Products
    "DATAPATTERNS",   # Data Patterns (India)
    "MTAR",           # MTAR Technologies
    "PARAS-DEFENCE",  # Paras Defence and Space Technologies
}


def is_defense_psu(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True if the ticker is a defense-sector name covered by
    the analyst-opinion-required disclaimer path.

    Mirrors the shape of :func:`is_etf` / :func:`is_regulated_utility`
    (strips .NS/.BO; accepts sector/industry though currently
    informational). Ticker membership in :data:`DEFENSE_PSU_TICKERS` is
    the single source of truth; ``sector`` / ``industry`` are accepted
    so the call site has the same signature as sibling classifiers and
    so a keyword fallback can be added later without churning callers.
    """
    if not ticker:
        return False
    bare = (
        ticker.replace(".NS", "")
        .replace(".BO", "")
        .upper()
    )
    return bare in DEFENSE_PSU_TICKERS


# ── REIT detection (PR #335 — feat/reit-asset-type-classifier) ─────
# Mirrors the ETF pattern. Indian REITs are SEBI-regulated pass-through
# trusts that distribute >=90% of NDCF as DPU. Generic FCF-DCF produces
# structurally wrong fair values.
REIT_TICKERS: set[str] = {
    "EMBASSY",
    "MINDSPACE",
    "BROOKFIELD",
    "NEXUS",
}


def is_reit(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True if `ticker` is a Real Estate Investment Trust (REIT).

    Three signals: curated ticker set, bare-symbol endswith "REIT",
    sector/industry text contains "REIT" / "real estate investment trust".
    """
    bare = ""
    if ticker:
        bare = (
            ticker.replace(".NS", "")
            .replace(".BO", "")
            .upper()
        )
        if bare in REIT_TICKERS:
            return True
        if bare.endswith("REIT"):
            return True

    blob = " ".join(
        (sector or "").lower().strip().split() +
        (industry or "").lower().strip().split()
    )
    if blob:
        if "real estate investment trust" in blob:
            return True
        tokens = blob.replace("-", " ").split()
        if "reit" in tokens or "reits" in tokens:
            return True

    return False


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

# ── Cement sector mistag fixes (added 2026-05-18, cement M&A truncation) ──
# AMBUJACEM surfaces from yfinance as sector="General/Diversified" rather
# than "Cement", which silently routes it through the generic DCF path
# and bypasses every cement-specific gate. CYCLICAL_TICKERS membership is
# keyed on the bare ticker so cyclical detection still fires, but the
# sector string is what propagates to the API response, frontend sector
# facet and peer-cohort queries. Force-pin to "Cement" so the override is
# applied at the same point as the financial-sector overrides above.
# Both bare and .NS-suffixed forms are seeded because some call sites look
# up the suffixed form before normalisation. See
# docs/design/cement-dcf-fix.md §3 (AMBUJACEM bucket A).
TICKER_SECTOR_OVERRIDES["AMBUJACEM"] = "Cement"
TICKER_SECTOR_OVERRIDES["AMBUJACEM.NS"] = "Cement"

# ── Realty developer sector mistag fixes (2026-05-18) ───────────
# Per docs/design/realty-developers-dcf-fix.md §5.2, three developer
# tickers come out of yfinance with broken sectors and block any
# Real-Estate routing until pinned:
#   LODHA       → "General/Diversified"  (mis-tag)
#   OBEROIRLTY  → NULL
#   GODREJPROP  → NULL
# Hard-override to "Real Estate" so the cohort engine + sector facet
# work immediately. The ingestion-side bug (yfinance NULL for OBEROI/
# GODREJ) is parallel work.
for _realty_t in ("LODHA", "OBEROIRLTY", "GODREJPROP"):
    TICKER_SECTOR_OVERRIDES[_realty_t] = "Real Estate"
    TICKER_SECTOR_OVERRIDES[f"{_realty_t}.NS"] = "Real Estate"


# ── Realty developer cohort (Approach C engine) ─────────────────
# Per docs/design/realty-developers-dcf-fix.md §5.1. Listed residential
# + mixed-use Indian developers. REITs are explicitly excluded — they
# have their own classifier (REIT_TICKERS) and their own engine.
REALTY_TICKERS: set[str] = {
    "DLF", "GODREJPROP", "LODHA", "OBEROIRLTY",
    "PRESTIGE", "PHOENIXLTD", "SOBHA", "BRIGADE",
    "MAHLIFE", "KEYSTONE", "MACROTECH", "NCC",
    "SHRIRAMPROP", "SUNTECK",
}


def is_realty_developer(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True if `ticker` is a listed Indian real-estate developer.

    Mirrors the is_reit / is_regulated_utility shape. REITs are
    explicitly excluded — a REIT ticker that happens to match a
    real-estate sector string must still route to the REIT engine.
    """
    bare = ""
    if ticker:
        bare = (
            ticker.replace(".NS", "")
            .replace(".BO", "")
            .upper()
        )
        # REITs are out of scope — they have their own classifier.
        if bare in REIT_TICKERS:
            return False
        if bare in REALTY_TICKERS:
            return True

    # Sector / industry fallback. Only fires if the curated set misses
    # the ticker; the routing branch in service.py additionally requires
    # a curation row in realty_land_bank_inputs, so a stray match here
    # cannot accidentally re-route a non-developer.
    blob = " ".join(
        (sector or "").lower().strip().split() +
        (industry or "").lower().strip().split()
    )
    if blob:
        if "real estate investment trust" in blob or "reit" in blob.split():
            return False
        if "real estate" in blob or "realty" in blob:
            return True
    return False


# USD → INR conversion rate for Financials rows tagged `currency = 'USD'`.
# TODO: source from a forex feed (RBI reference rate) rather than a constant.
USD_INR_RATE = 83.5


# ─────────────────────────────────────────────────────────────────────
# Holding companies / SPVs / pure investment vehicles
# (added 2026-05-17, structural data-quality fix #4)
#
# These businesses have no operating revenue — they own equity stakes
# in subsidiaries and collect dividends. Their reported revenue_cr is
# typically <100 Cr and their CFO/FCF is dominated by dividend receipts
# and stake monetisations, both of which are intermittent and bear no
# relation to intrinsic value. Running DCF on these names produces
# absurd FVs in both directions (GAYAHWS surfaced as cfo_cr=7.37 bn
# pre-fix, which the DCF engine then projected forward as steady-state
# cash generation).
#
# The right valuation framework is Sum-Of-The-Parts (SOTP) over the
# underlying stakes — that engine is on the Q3 roadmap. Until it
# ships, we detect these names and short-circuit the DCF entirely:
# verdict = data_limited, valuation_model = holding_company_sotp_required,
# no FV emitted. The frontend renders an SOTP caveat banner.
#
# Detection = (curated allow-list) OR (auto-detect on revenue/industry/
# market-cap signals). Auto-detect is intentionally conservative —
# revenue must be near-zero AND industry/sector keyword must match AND
# market-cap must be material (so we don't tag defunct shells with
# revenue=0 just because they're inactive).
# ─────────────────────────────────────────────────────────────────────

HOLDING_COMPANIES: set[str] = {
    # Pure holding companies (own stakes in operating subsidiaries,
    # collect dividends, no operating business of their own).
    "BAJAJHLDNG",       # Bajaj Holdings & Investment
    "TATAINVEST",       # Tata Investment Corporation
    "MCLEODRUSS",       # McLeod Russel India (tea estate holdco)
    "NDTV",             # New Delhi Television (holdco for media stakes)
    "NETWORK18",        # Network18 Media (Reliance media holdco)
    "GAYAHWS",          # Gayatri Highways (toll-road SPV)
    "MOIL",             # MOIL Limited (manganese holding/leasing)
    "PILANIINVS",       # Pilani Investment & Industries
    "WILLIAMAGR",       # Williamson Magor & Co (Eveready / McLeod holdco)
    "SUMMITSEC",        # Summit Securities
    "KAMAHOLD",         # Kama Holdings (SRF promoter holdco)
    "MAHSCOOTER",       # Maharashtra Scooters (Bajaj group holdco)
    # GRASIM — holding for UltraTech Cement + VSF businesses.
    # Standalone DCF misleading; needs SOTP.
    "GRASIM",
}


# Sector / industry keyword fragments that mark a ticker as a holding
# company candidate for auto-detection. Matched case-insensitively as
# substrings of the resolved sector or industry label.
_HOLDING_INDUSTRY_KEYWORDS = (
    "holding",
    "investment",      # "Investment Holdings", "Investment Trust"
    "diversified",     # NIC 64200 maps here in NSE classifications
    "spv",
    "special purpose",
)

# NIC industrial classification code 64200 = "Activities of holding
# companies". Stored as a string in some upstream feeds.
_HOLDING_NIC_CODES = {"64200", "64201", "64202"}


def is_holding_company(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
    revenue_cr: float | None = None,
    market_cap_cr: float | None = None,
    nic_code: str | None = None,
) -> bool:
    """Return True if the ticker is a holding company / SPV / pure
    investment vehicle for which DCF is structurally inappropriate.

    Two independent signals — match on either:

      1. Ticker membership in :data:`HOLDING_COMPANIES` (curated
         allow-list, highest priority; bypasses every gate).
      2. Auto-detect: ALL THREE must be true —
           - revenue_cr < 100 (near-zero operating revenue)
           - sector OR industry OR NIC code matches a holding-co
             keyword (so dormant operating businesses aren't tagged)
           - market_cap_cr > 100 (so defunct shells aren't tagged)

    The auto-detect path is conservative on purpose: a false positive
    here means we silently drop the DCF for a real operating company.
    The curated allow-list is the primary defence; auto-detect is the
    safety net for names we haven't enumerated yet.
    """
    if ticker:
        bare = (
            ticker.replace(".NS", "")
            .replace(".BO", "")
            .upper()
        )
        if bare in HOLDING_COMPANIES:
            return True

    # Auto-detect requires all three signals.
    if revenue_cr is None or market_cap_cr is None:
        return False
    try:
        if float(revenue_cr) >= 100.0:
            return False
        if float(market_cap_cr) <= 100.0:
            return False
    except (TypeError, ValueError):
        return False

    blob = " ".join(
        (sector or "").lower().strip().split() +
        (industry or "").lower().strip().split()
    )
    keyword_hit = any(k in blob for k in _HOLDING_INDUSTRY_KEYWORDS)
    nic_hit = bool(nic_code) and str(nic_code).strip() in _HOLDING_NIC_CODES
    return keyword_hit or nic_hit


# ═══════════════════════════════════════════════════════════════
# RESTORED 2026-05-18 — FMCG brand-premium + Capital Goods sections
# were lost during a manual rebase of PR #333 (Defense flag) when
# `git checkout --theirs` overwrote the FMCG + Capital Goods additions
# already on main. Symbols below match the squashed commits 0c250f9
# (FMCG #336) and 352b1fb (Capital Goods #337) — single source of
# truth. Imports in service.py reference these symbols; without them
# the backend fails to start (Railway healthcheck timeout).
# ═══════════════════════════════════════════════════════════════
# ─────────────────────────────────────────────────────────────────────
# Brand-moat premium overlay (added 2026-05-18, PR
# feat/fmcg-brand-moat-overlay — see docs/design/fmcg-dcf-fix.md)
#
# Generic FCF-DCF with terminal_g=4% and ~17.9x terminal multiple cannot
# reach the 50-70x P/E that markets pay for the permanent-brand-moat
# tail of Indian FMCG (NESTLE/Maggi, BRITANNIA/Good Day, MARICO/
# Parachute, GODREJCP/Cinthol-Goodknight, PIDILITIND/Fevicol,
# GILLETTE/razors). The 4% terminal pin caps the expected compounding
# at India's nominal-GDP rate and leaves 20-50% of brand-permanence
# value unrecognised for this sub-cohort.
#
# This is a CURATED per-ticker multiplier applied AFTER the generic DCF
# produces `iv`, AND ONLY when the resolved sector is FMCG (belt-and-
# braces: never apply outside FMCG even if a ticker is wrongly
# classified into the dict). The overlay multiplies bear / base / bull
# IVs by the same factor so dispersion ratio is preserved. The raw
# pre-premium FV is appended to `data_issues` for audit transparency.
#
# Governance gates for adding a ticker (per design doc §9):
#   (a) EV/EBITDA > 30
#   (b) ROCE > 25%
#   (c) named brand monopoly or duopoly
#   (d) MoS gap > 25% in current prod
#   (e) explicit sign-off in PR review
#
# Multipliers are calibrated to street consensus EV/EBITDA premiums to
# the FMCG sector median; revisit annually. Bare ticker form (no .NS /
# .BO suffix). Tickers NOT in this dict (HUL, ITC, DABUR, COLPAL, PGHH,
# AKZOINDIA, BAJAJCON, EMAMI, JYOTHYLAB, VBL, TASTYBITE) deliberately
# stay on the generic path — they already land within ±20% of CMP and a
# blanket sector-wide multiplier would over-fit them.
# ─────────────────────────────────────────────────────────────────────

BRAND_MOAT_PREMIUM_TICKERS: dict[str, float] = {
    "NESTLEIND":  1.45,  # Maggi / Cerelac / Nescafe monopoly
    "BRITANNIA":  1.25,  # Good Day / Marie premium biscuit category leader
    "MARICO":     1.20,  # Parachute coconut-oil monopoly + Saffola edible-oil
    "GODREJCP":   1.20,  # Cinthol / Goodknight household-insecticide leader
    "PIDILITIND": 1.35,  # Fevicol / Fevikwik adhesives category-killer
    "GILLETTE":   1.25,  # premium razors monopoly
    "TATACONSUM": 1.10,  # Tata Tea / Tetley + Tata Salt brand
    "DABUR":      1.10,  # Dabur Honey / Chyawanprash herbal brand
    "EMAMILTD":   1.10,  # Boroplus / Navratna brand
    "JYOTHYLAB":  1.10,  # Ujala detergent / fabric-whitener monopoly
}


# Sector strings (case-insensitive) that count as "FMCG" for the
# brand-moat premium gate. Mirrors the canonical labels seeded into
# SECTOR_OVERRIDES (Tobacco / Packaged Foods / Household & Personal
# Products / Beverages-Non-Alcoholic all collapse to "FMCG") plus the
# yfinance long-form label ("Consumer Defensive") which some tickers
# surface with directly.
_FMCG_SECTOR_LABELS: set[str] = {
    "fmcg",
    "consumer defensive",
    "consumer staples",
}


def is_fmcg_sector(sector: str | None) -> bool:
    """Return True if `sector` resolves to the FMCG bucket for the
    brand-moat premium gate. Case-insensitive, whitespace-tolerant.
    """
    if not sector:
        return False
    return sector.strip().lower() in _FMCG_SECTOR_LABELS


def get_brand_moat_multiplier(ticker: str | None) -> float:
    """Return the brand-moat multiplier for `ticker` (1.0 if not in the
    curated set). Strips .NS / .BO suffix and uppercases before lookup
    so call sites can pass either form.

    NOTE: the SECTOR GATE is enforced at the call site
    (backend/services/analysis/service.py) — this helper only does the
    dict lookup. Returning > 1.0 here does NOT imply the premium will
    be applied; the caller must additionally check
    :func:`is_fmcg_sector` so a wrongly-classified ticker never gets
    the multiplier applied outside FMCG.
    """
    if not ticker:
        return 1.0
    # Uppercase first so mixed-case inputs ("nestleind.ns") strip the
    # suffix correctly — the legacy str.replace pattern elsewhere in
    # this module is case-sensitive and would leak ".ns" through.
    bare = (
        ticker.upper()
        .replace(".NS", "")
        .replace(".BO", "")
    )
    return BRAND_MOAT_PREMIUM_TICKERS.get(bare, 1.0)


# ── Capital Goods sector mistag fixes (added 2026-05-18, v113) ──────────
# yfinance routinely surfaces bearings / abrasives / defence-EMS names
# under unrelated buckets ("Auto Components" for TIMKEN/SCHAEFFLER —
# historically true but ~50% of revenue is now industrial / general
# engineering; "General/Diversified" for GRINDWELL — abrasives is a
# capital-goods consumable; "Tech Hardware/Electronics" for KAYNES —
# the defence-EMS franchise is project-driven capital goods).
#
# Routing them to "Capital Goods" wires them into:
#   - is_capital_goods() classifier
#   - sector_benchmarks.py::capital_goods (fcf_conv=0.60, wc_days=90)
#   - the 7y WC-smoothed FCF candidate in _compute_fcf_base
# See docs/design/capital-goods-dcf-fix.md §4 (Approach B + sector-mistag).
#
# Note on VOLTAS/BLUESTARCO/HAVELLS: per the design doc §4, these
# stay tagged "Consumer Durables" (yfinance is technically right —
# they are durables-facing) but are flagged via HYBRID_INDUSTRIAL_DURABLES
# so the capital-goods FCF normalisation still fires (their B2B project
# segments — MEP / commercial refrigeration / industrial cables — are
# the under-valued tail). Pure sector override would cascade to peer
# tables / hex axes etc. — bad.
for _t in ("TIMKEN", "SCHAEFFLER", "GRINDWELL", "KAYNES"):
    TICKER_SECTOR_OVERRIDES[_t] = "Capital Goods"
    TICKER_SECTOR_OVERRIDES[f"{_t}.NS"] = "Capital Goods"


# ─────────────────────────────────────────────────────────────────────
# Capital Goods classifier (added 2026-05-18, v113,
# PR feat/capital-goods-sector-engine)
#
# 18 capital-goods / industrial tickers were broken bidirectionally
# (15/18 outside ±30% of consensus). Root cause: lumpy project FCF +
# working-capital absorption. Trailing 1-3y FCF for a turnkey project
# business is meaningless — one milestone crossing inflates FCF, one
# advance-payment WC build crashes it. The 5y revenue CAGR is null for
# 10/18 names because revenue itself oscillates with project execution.
#
# This classifier routes detected tickers through a new branch in
# models/forecaster._compute_fcf_base:
#   - 7-year WC-smoothed signed-median FCF candidate (subtracts the
#     yearly Δ inventory + Δ receivables - Δ payables to remove WC
#     noise; signed median preserves legitimate negative-cycle years).
#   - Hyper-growth fade for `revenue_cagr_3y > 0.30` (KAYNES style —
#     30%+ cannot be perpetual; terminal_g pulled toward min(cagr×0.5,
#     0.06) so the perpetuity cap doesn't compound to infinity).
#
# Detection = (curated allow-list) OR (sector keyword match) OR
# (industry keyword match). Curated set is primary defence; sector
# fallback catches yfinance "Industrials" / "Engineering" / "Capital
# Goods" buckets.
# ─────────────────────────────────────────────────────────────────────

CAPITAL_GOODS_TICKERS: set[str] = {
    # EPC / turnkey engineering (under-valued by trailing FCF; WC heavy)
    "LT",            # Larsen & Toubro
    "KEC",           # KEC International (T&D EPC)
    "ISGEC",         # ISGEC Heavy Engineering
    "BHEL",          # PSU thermal-power equipment (regime change post-2023)
    "GMMPFAUDLR",    # GMM Pfaudler (glass-lined reactors)
    "ELGIEQUIP",     # Elgi Equipments (air compressors)
    # Process / plant engineering
    "THERMAX",       # boiler + utility-plant engineering
    "CUMMINSIND",    # Cummins India (gen-sets, engines)
    "SIEMENS",       # Siemens India (post-Siemens-Energy demerger)
    "ABB",           # ABB India
    "CGPOWER",       # CG Power & Industrial Solutions
    # Bearings / abrasives / industrial consumables (sector-mistagged)
    "TIMKEN",        # Timken India (bearings — yfinance tags Auto Components)
    "SCHAEFFLER",    # Schaeffler India (bearings — yfinance tags Auto Components)
    "GRINDWELL",     # Grindwell Norton (abrasives — yfinance tags General)
    "AIAENG",        # AIA Engineering (grinding media)
    "KIRLOSKARIND",  # Kirloskar Industries
    "KIRLOSKAROIL",  # Kirloskar Oil Engines
    # Defence / EMS hyper-grower (sector-mistagged Tech Hardware)
    "KAYNES",        # Kaynes Technology (defence + EMS, hyper-growth)
    # Adjacent (engine OEMs, gearbox, motors)
    "GREAVESCOT",    # Greaves Cotton
}


_CAPITAL_GOODS_SECTOR_KEYWORDS = (
    "capital goods",
    "industrials",
    "engineering",
    "engineering & construction",
    "engineering and construction",
    "heavy electrical equipment",
    "industrial machinery",
    "construction machinery",
    "electrical equipment",
)

_CAPITAL_GOODS_INDUSTRY_KEYWORDS = (
    "specialty industrial machinery",
    "industrial machinery",
    "electrical equipment",
    "engineering",
    "heavy machinery",
    "bearings",
    "abrasives",
    "construction & engineering",
)


# Hybrid industrial / consumer-durable tickers. Sector stays
# "Consumer Durables" (yfinance is right for HAVELLS/VOLTAS/BLUESTARCO
# — they DO sell to consumers) but their B2B project tail (VOLTAS MEP
# / HAVELLS industrial cable / BLUESTAR commercial refrigeration) is
# what trailing-FCF DCF mis-prices. Flag so _compute_fcf_base still
# applies the WC-smoothed 7y FCF normalisation.
HYBRID_INDUSTRIAL_DURABLES: set[str] = {
    "VOLTAS",
    "BLUESTARCO",
    "HAVELLS",
}


# Per-ticker regime-change cutoffs. For BHEL the pre-2023 decade was
# structural decline (PSU thermal-power orderbook contraction); the
# post-2023 Make-in-India + defence-orders revival is a different
# business. Restrict the FCF window to years >= cutoff so the trailing
# median doesn't reflect a dead-cycle that no longer applies.
CAPITAL_GOODS_REGIME_CHANGE: dict[str, int] = {
    "BHEL": 2023,
}


# Tickers explicitly classified as cap-goods hyper-growers (rev_3y
# regularly > 30%). Hyper-growth branch in _compute_fcf_base fades
# terminal_g down so the perpetuity isn't anchored on a 40% growth
# rate that cannot be perpetual.
CAPITAL_GOODS_HYPER_GROWTH: set[str] = {
    "KAYNES",
}


def is_capital_goods(
    ticker: str | None,
    sector: str | None = None,
    industry: str | None = None,
) -> bool:
    """Return True if the ticker should route through the capital-goods
    sector engine in :func:`models.forecaster._compute_fcf_base`.

    Three independent signals — match on any:

      1. Ticker membership in :data:`CAPITAL_GOODS_TICKERS` (curated
         allow-list) or :data:`HYBRID_INDUSTRIAL_DURABLES` (durables
         with a material B2B project tail).
      2. Sector string matches one of the cap-goods keywords
         ("Capital Goods", "Industrials", "Engineering", ...).
      3. Industry string contains one of the cap-goods industry
         keywords ("Specialty Industrial Machinery", "Bearings",
         "Abrasives", "Electrical Equipment", ...).

    Mirrors the shape of :func:`is_inventory_heavy` and
    :func:`is_capex_super_cyclical`. Used by the forecaster to route
    detected tickers through the 7y WC-smoothed FCF candidate and the
    hyper-growth terminal fade branch.
    """
    bare = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
    if bare and (
        bare in CAPITAL_GOODS_TICKERS
        or bare in HYBRID_INDUSTRIAL_DURABLES
    ):
        return True
    s = (sector or "").strip().lower()
    if s and any(k == s or k in s for k in _CAPITAL_GOODS_SECTOR_KEYWORDS):
        return True
    i = (industry or "").strip().lower()
    if i and any(k in i for k in _CAPITAL_GOODS_INDUSTRY_KEYWORDS):
        return True
    return False

