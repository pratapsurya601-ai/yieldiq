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
