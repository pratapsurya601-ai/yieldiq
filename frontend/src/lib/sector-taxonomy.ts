// frontend/src/lib/sector-taxonomy.ts
// ═══════════════════════════════════════════════════════════════
// Canonical sector taxonomy — frontend mirror of
// backend/services/sector_taxonomy.py.
//
// Why mirror instead of fetch?
// ----------------------------
// The earnings calendar, screener, watchlist, and (Phase 2) the
// /sectors index all need to normalize sector strings during render.
// A network round-trip per render would be absurd. The taxonomy is
// small (13 + ~40 aliases) and changes ~once a quarter, so an
// inlined copy with a "keep in sync" comment is the pragmatic call.
//
// SYNC RULE: when you change CANONICAL_SECTORS or SECTOR_ALIAS_MAP
// here, mirror the change in backend/services/sector_taxonomy.py.
// The PR template asks you to confirm both files moved together.
// ═══════════════════════════════════════════════════════════════

/** 13 canonical sectors. Order matches the backend constant. */
export const CANONICAL_SECTORS = [
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
] as const

export type CanonicalSector = (typeof CANONICAL_SECTORS)[number]

/**
 * Lowercase-keyed alias map. Lookup MUST lowercase-strip the input.
 * Unknown sectors fall through unchanged (see normalizeSector).
 */
export const SECTOR_ALIAS_MAP: Record<string, string> = {
  // Auto family
  "auto": "Auto",
  "auto oem": "Auto",
  "automobile": "Auto",
  "automobiles": "Auto",
  "auto components": "Auto",
  "auto component": "Auto",
  // Banks (generic)
  "bank": "Bank",
  "banks": "Bank",
  "banking": "Bank",
  // Private banks
  "private bank": "Private Bank",
  "private banks": "Private Bank",
  "private sector bank": "Private Bank",
  // PSU banks
  "psu bank": "PSU Bank",
  "psu banks": "PSU Bank",
  "public sector bank": "PSU Bank",
  // Consumer durables
  "consumer durables": "Consumer Durables",
  "consumer durable": "Consumer Durables",
  "durables": "Consumer Durables",
  // Energy
  "energy": "Energy",
  "oil & gas": "Energy",
  "oil and gas": "Energy",
  "power": "Energy",
  // Financial services (non-bank)
  "financial services": "Financial Services",
  "finance": "Financial Services",
  "nbfc": "Financial Services",
  "insurance": "Financial Services",
  // FMCG
  "fmcg": "FMCG",
  "consumer staples": "FMCG",
  "fast moving consumer goods": "FMCG",
  // IT
  "it": "IT Services",
  "it services": "IT Services",
  "technology": "IT Services",
  "information technology": "IT Services",
  "software": "IT Services",
  // Media
  "media": "Media",
  "media & entertainment": "Media",
  // Metal
  "metal": "Metal",
  "metals": "Metal",
  "metals & mining": "Metal",
  "mining": "Metal",
  // Pharma / healthcare
  "pharma": "Pharma",
  "pharmaceuticals": "Pharma",
  "pharmaceutical": "Pharma",
  "healthcare": "Pharma",
  "health care": "Pharma",
  // Real estate
  "real estate": "Real Estate",
  "realty": "Real Estate",
  "real estate investment": "Real Estate",
}

/**
 * Map a raw sector string to its canonical form.
 *
 * Returns null for null/undefined/empty input. Unknown sectors fall
 * through UNCHANGED (with whitespace stripped) — never silently erase
 * a sector we haven't explicitly mapped.
 */
export function normalizeSector(raw: string | null | undefined): string | null {
  if (!raw) return null
  const stripped = raw.trim()
  if (!stripped) return null
  return SECTOR_ALIAS_MAP[stripped.toLowerCase()] ?? stripped
}

/**
 * Canonical sector → URL slug.
 *   "IT Services"     → "it-services"
 *   "Real Estate"     → "real-estate"
 *   "FMCG"            → "fmcg"
 */
export function sectorSlug(sector: string): string {
  if (!sector) return ""
  return sector
    .trim()
    .toLowerCase()
    .replace(/&/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .join("-")
}

const SLUG_TO_SECTOR: Record<string, string> = Object.fromEntries(
  CANONICAL_SECTORS.map(s => [sectorSlug(s), s])
)

/**
 * URL slug → canonical sector. Returns null if slug is not one of
 * the 13 canonical sectors.
 */
export function sectorFromSlug(slug: string): string | null {
  if (!slug) return null
  return SLUG_TO_SECTOR[slug.trim().toLowerCase()] ?? null
}
