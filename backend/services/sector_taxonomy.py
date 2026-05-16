# backend/services/sector_taxonomy.py
# ═══════════════════════════════════════════════════════════════
# Canonical sector taxonomy for YieldIQ.
#
# Purpose
# -------
# Raw sector labels arrive from three sources that disagree on
# spelling and granularity (yfinance, NSE corporate-event feed,
# the screener cache). Some examples observed in prod:
#
#   "Automobiles", "Auto OEM", "Auto components"   → Auto
#   "Healthcare", "Pharmaceuticals"                 → Pharma
#   "Realty", "Real Estate Investment"              → Real Estate
#   "Bank", "Banks", "Banking"                      → Bank
#
# Without a single normalizer, the sector deep-dive page would
# fragment one logical sector across multiple buckets and the
# medians would be computed on partial cohorts.
#
# This module owns the 13 canonical sectors and a lowercase-keyed
# alias map. Both the backend aggregator and the frontend taxonomy
# (frontend/src/lib/sector-taxonomy.ts) MUST stay in sync — when
# you add a sector or alias here, mirror it there.
#
# See also
# --------
#   backend/services/sector_aggregator.py   (consumer)
#   frontend/src/lib/sector-taxonomy.ts     (mirror)
#   tests/test_sector_aggregator.py         (alias coverage)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Optional

# ── 13 canonical sectors ────────────────────────────────────────
# Stable order matters: PR/UI may iterate this list to render
# cards. Keep alphabetical except where a parent group reads
# better (Bank / Private Bank / PSU Bank are separate buckets
# because the verdict thresholds behave differently for PSUs).
CANONICAL_SECTORS: list[str] = [
    "Auto",
    "Bank",
    "Consumer Durables",
    "Energy",
    "Financial Services",
    "FMCG",
    "IT Services",
    "Media",
    "Metal",
    "Pharma",
    "Private Bank",
    "PSU Bank",
    "Real Estate",
]

# Lowercase-keyed alias map. Lookups MUST lowercase-strip the input
# first (see normalize_sector). Keep keys lowercase here — Python
# does not have a case-insensitive dict and a CI lookup loop would
# be O(n) per call.
SECTOR_ALIAS_MAP: dict[str, str] = {
    # Auto family
    "auto": "Auto",
    "auto oem": "Auto",
    "automobile": "Auto",
    "automobiles": "Auto",
    "auto components": "Auto",
    "auto component": "Auto",
    # Banks (generic)
    "bank": "Bank",
    "banks": "Bank",
    "banking": "Bank",
    # Private banks
    "private bank": "Private Bank",
    "private banks": "Private Bank",
    "private sector bank": "Private Bank",
    # PSU banks
    "psu bank": "PSU Bank",
    "psu banks": "PSU Bank",
    "public sector bank": "PSU Bank",
    # Consumer durables
    "consumer durables": "Consumer Durables",
    "consumer durable": "Consumer Durables",
    "durables": "Consumer Durables",
    # Energy
    "energy": "Energy",
    "oil & gas": "Energy",
    "oil and gas": "Energy",
    "power": "Energy",
    # Financial services (non-bank)
    "financial services": "Financial Services",
    "finance": "Financial Services",
    "nbfc": "Financial Services",
    "insurance": "Financial Services",
    # FMCG
    "fmcg": "FMCG",
    "consumer staples": "FMCG",
    "fast moving consumer goods": "FMCG",
    # IT
    "it": "IT Services",
    "it services": "IT Services",
    "technology": "IT Services",
    "information technology": "IT Services",
    "software": "IT Services",
    # Media
    "media": "Media",
    "media & entertainment": "Media",
    # Metal
    "metal": "Metal",
    "metals": "Metal",
    "metals & mining": "Metal",
    "mining": "Metal",
    # Pharma / healthcare
    "pharma": "Pharma",
    "pharmaceuticals": "Pharma",
    "pharmaceutical": "Pharma",
    "healthcare": "Pharma",
    "health care": "Pharma",
    # Real estate
    "real estate": "Real Estate",
    "realty": "Real Estate",
    "real estate investment": "Real Estate",
}


def normalize_sector(raw: Optional[str]) -> Optional[str]:
    """Map a raw sector string to its canonical form.

    Returns None for None/empty input. Unknown sectors fall through
    UNCHANGED (with original casing/whitespace stripped) — never
    silently erase a sector we haven't explicitly mapped, because
    the screener may be carrying a new NSE bucket we haven't seen.
    """
    if not raw:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return SECTOR_ALIAS_MAP.get(stripped.lower(), stripped)


# ════════════════════════════════════════════════════════════════
# Industry-aware canonical mapping (2026-05-16 audit follow-up)
#
# The plain alias map can't disambiguate yfinance broad labels like
# "Basic Materials" / "Industrials" / "Consumer Cyclical" /
# "Communication Services" / "Financial Services" — these each fan
# out into ~10 NSE-level industries that belong in different YieldIQ
# canonical buckets (e.g. "Consumer Cyclical / Apparel Retail" is
# Consumer Durables for our purposes; "Consumer Cyclical / Auto
# Parts" is Auto). The (raw_sector, industry_substring) → canonical
# table below is consulted BEFORE the plain alias map.
#
# Ordering inside each list matters: the first substring whose
# lowercase form appears in the lowercase industry wins.
# ════════════════════════════════════════════════════════════════
INDUSTRY_CANONICAL_RULES: dict[str, list[tuple[str, str]]] = {
    # raw sector -> list of (industry substring, canonical sector)
    "basic materials": [
        ("steel", "Metal"),
        ("aluminum", "Metal"),
        ("copper", "Metal"),
        ("metals", "Metal"),
        ("mining", "Metal"),
        ("coking coal", "Energy"),
        ("specialty chemicals", "Energy"),  # bucket as Energy/Chem-adjacent
        ("chemicals", "Energy"),
        ("agricultural inputs", "FMCG"),
        ("building materials", "Real Estate"),
        ("paper", "Metal"),  # fallback bucket for forest/paper
        ("lumber", "Metal"),
    ],
    "consumer cyclical": [
        ("auto parts", "Auto"),
        ("auto manufacturers", "Auto"),
        ("auto & truck", "Auto"),
        ("apparel", "Consumer Durables"),
        ("textile", "Consumer Durables"),
        ("footwear", "Consumer Durables"),
        ("luxury", "Consumer Durables"),
        ("furnishings", "Consumer Durables"),
        ("packaging", "Consumer Durables"),
        ("lodging", "Consumer Durables"),
        ("travel", "Consumer Durables"),
        ("restaurants", "Consumer Durables"),
        ("leisure", "Consumer Durables"),
        ("resorts", "Consumer Durables"),
        ("retail", "Consumer Durables"),
        ("stores", "Consumer Durables"),
        ("home improvement", "Consumer Durables"),
    ],
    "consumer defensive": [
        ("tobacco", "FMCG"),
        ("packaged foods", "FMCG"),
        ("confectioners", "FMCG"),
        ("farm products", "FMCG"),
        ("beverages", "FMCG"),
        ("household", "FMCG"),
        ("personal products", "FMCG"),
        ("food distribution", "FMCG"),
        ("grocery", "FMCG"),
        ("discount stores", "FMCG"),
        ("education", "Media"),  # ed-tech reads closer to Media than FMCG
    ],
    "consumer services": [
        ("leisure", "Consumer Durables"),
        ("retailing", "Consumer Durables"),
        ("", "Consumer Durables"),
    ],
    "communication services": [
        ("telecom", "Media"),
        ("broadcasting", "Media"),
        ("publishing", "Media"),
        ("entertainment", "Media"),
        ("advertising", "Media"),
        ("internet content", "Media"),
    ],
    "industrials": [
        ("aerospace", "Auto"),  # defence/aerospace tracks with auto cohort
        ("airlines", "Auto"),
        ("freight", "Auto"),
        ("trucking", "Auto"),
        ("railroads", "Auto"),
        ("marine", "Auto"),
        ("airports", "Auto"),
        # Everything else industrial reads as Metal-cohort heavy capex
        ("engineering", "Metal"),
        ("construction", "Metal"),
        ("machinery", "Metal"),
        ("electrical", "Metal"),
        ("building products", "Real Estate"),
        ("metal fabrication", "Metal"),
        ("conglomerates", "Metal"),
        ("infrastructure", "Energy"),
        ("waste management", "Energy"),
        ("business services", "Media"),
        ("staffing", "Media"),
        ("consulting", "Media"),
        ("rental", "Media"),
        ("distribution", "Media"),
        ("tools", "Metal"),
        ("equipment & supplies", "Metal"),
        ("pollution", "Energy"),
        ("security", "Media"),
        # Catch-all: anything else industrial buckets as Metal-cohort.
        ("", "Metal"),
    ],
    "financial services": [
        # Banking sub-types — only when industry hints at it
        ("private bank", "Private Bank"),
        ("psu bank", "PSU Bank"),
        ("banks - regional", "Bank"),
        # Everything else inside "Financial Services" stays as the
        # canonical "Financial Services" bucket (NBFC, AMC, insurance,
        # credit, capital markets).
    ],
    "utilities": [
        ("renewable", "Energy"),
        ("electric", "Energy"),
        ("gas", "Energy"),
        ("water", "Energy"),
        ("power", "Energy"),
    ],
    "energy": [
        ("oil", "Energy"),
        ("gas", "Energy"),
        ("coal", "Energy"),
    ],
    "pharma": [
        # All pharma sub-industries roll up to Pharma.
        ("", "Pharma"),
    ],
    "real estate": [
        ("", "Real Estate"),
    ],
    "forest materials": [
        ("", "Metal"),
    ],
    "textiles": [
        ("", "Consumer Durables"),
    ],
    "services": [
        ("", "Media"),
    ],
    "diversified": [
        ("", "Financial Services"),
    ],
    "oil gas & consumable fuels": [
        ("", "Energy"),
    ],
    "media entertainment & publication": [
        ("", "Media"),
    ],
    "construction": [
        ("", "Real Estate"),
    ],
    "automobile and auto components": [
        ("", "Auto"),
    ],
    "capital goods": [
        ("", "Metal"),
    ],
    "chemicals": [
        ("", "Energy"),
    ],
}


# ════════════════════════════════════════════════════════════════
# Per-ticker overrides — the truth source for mis-tagged names the
# 2026-05-16 audit caught (and any future hand-resolved cases).
# Wins over both INDUSTRY_CANONICAL_RULES and SECTOR_ALIAS_MAP.
# ════════════════════════════════════════════════════════════════
TICKER_CANONICAL_OVERRIDES: dict[str, tuple[str, str]] = {
    # (canonical_sector, canonical_industry)
    # Insurance aggregator listed under Financial Services / Insurance Brokers
    "POLICYBZR": ("Financial Services", "Insurance"),
    # Diversified financial holdco — was tagged Insurance - Life by mistake
    "RELIGARE":  ("Financial Services", "NBFC"),
    # Life / general insurers — industry was set to "Nifty Financial Services"
    "HDFCLIFE":  ("Financial Services", "Insurance"),
    "ICICIGI":   ("Financial Services", "Insurance"),
    "SBILIFE":   ("Financial Services", "Insurance"),
    "ICICIPRULI": ("Financial Services", "Insurance"),
    "LICI":      ("Financial Services", "Insurance"),
    "MAXLIFE":   ("Financial Services", "Insurance"),
    "STARHEALTH": ("Financial Services", "Insurance"),
    "GICRE":     ("Financial Services", "Insurance"),
    "NIACL":     ("Financial Services", "Insurance"),
    # Specialty retailers/services that read better as Consumer Durables / Pharma
    "GOCOLORS":  ("Consumer Durables", "Apparel Retail"),
    "MEDPLUS":   ("Pharma", "Pharmaceutical Retailers"),
    # Credit cards roll into NBFC under Financial Services
    "SBICARD":   ("Financial Services", "NBFC"),
}


def to_canonical(
    raw_sector: Optional[str],
    raw_industry: Optional[str] = None,
    ticker: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """Return (canonical_sector, canonical_industry) for a row.

    Resolution order:
      1. Per-ticker override (TICKER_CANONICAL_OVERRIDES).
      2. Industry-aware rule (INDUSTRY_CANONICAL_RULES[sector_lc]).
      3. Plain alias map (SECTOR_ALIAS_MAP).
      4. Fallback to "Unknown" canonical so cohort queries never break.

    canonical_industry is the raw industry by default (preserving the
    finer-grained NSE/yfinance label) unless an override supplies one.
    """
    # 1. Ticker override wins.
    if ticker:
        tkr = ticker.strip().upper()
        if tkr in TICKER_CANONICAL_OVERRIDES:
            canon_sec, canon_ind = TICKER_CANONICAL_OVERRIDES[tkr]
            return canon_sec, canon_ind

    canon_industry = (raw_industry or "").strip() or None

    if not raw_sector:
        return "Unknown", canon_industry

    sector_lc = raw_sector.strip().lower()
    industry_lc = (raw_industry or "").strip().lower()

    # 2. Industry-aware rule.
    rules = INDUSTRY_CANONICAL_RULES.get(sector_lc)
    if rules:
        for ind_sub, canon in rules:
            if ind_sub == "" or (industry_lc and ind_sub in industry_lc):
                return canon, canon_industry

    # 3. Plain alias map (handles "Banks" / "FMCG" / "IT Services" etc.).
    aliased = SECTOR_ALIAS_MAP.get(sector_lc)
    if aliased:
        return aliased, canon_industry

    # 4. Last-ditch: if the raw sector is already a canonical name,
    #    return it verbatim. Otherwise bucket as Unknown rather than
    #    leaking a one-off NSE label into cohort SQL.
    if raw_sector.strip() in CANONICAL_SECTORS:
        return raw_sector.strip(), canon_industry

    return "Unknown", canon_industry


def sector_slug(sector: str) -> str:
    """Canonical sector → URL slug.

    "IT Services"     → "it-services"
    "Real Estate"     → "real-estate"
    "FMCG"            → "fmcg"
    "Consumer Durables" → "consumer-durables"

    Lowercase, spaces → hyphens, ampersands stripped. The inverse
    (sector_from_slug) round-trips for any value in CANONICAL_SECTORS.
    """
    if not sector:
        return ""
    s = sector.strip().lower()
    # Drop ampersands first so " & " doesn't become "--".
    s = s.replace("&", "")
    # Collapse runs of whitespace, then convert to hyphens.
    s = "-".join(s.split())
    return s


# Pre-built reverse map for sector_from_slug. Built once at import.
_SLUG_TO_SECTOR: dict[str, str] = {sector_slug(s): s for s in CANONICAL_SECTORS}


def sector_from_slug(slug: str) -> Optional[str]:
    """URL slug → canonical sector. None if slug unknown.

    Only canonical sectors are returned; this is the gate the router
    uses to decide between 200 and 404.
    """
    if not slug:
        return None
    return _SLUG_TO_SECTOR.get(slug.strip().lower())
