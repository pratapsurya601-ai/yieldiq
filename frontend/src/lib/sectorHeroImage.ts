/**
 * sectorHeroImage — map a raw sector string to a contextual hero photo.
 *
 * The 18 hero-sector slugs live under
 * ``frontend/public/hero-sectors/{slug}.webp`` (downloaded by
 * ``scripts/fetch_sector_heroes.py``). Backend sector taxonomy is
 * messier than the slug list (90+ distinct strings observed in the
 * 333-stock canary universe), so this module groups every observed
 * sector into one of the 18 visual buckets. Unmapped values fall
 * through to ``default.webp``.
 *
 * Matching is case-insensitive substring against a few keywords —
 * deliberately tolerant rather than an exact-match table, so a new
 * backend sector ("NBFC - Insurance") routes to the closest visual
 * bucket without needing a code edit.
 */

/** Stable slug list — every entry MUST have a matching public/hero-sectors/{slug}.webp. */
export type HeroSectorSlug =
  | "banking"
  | "nbfc"
  | "insurance"
  | "it_services"
  | "fmcg"
  | "auto"
  | "pharma"
  | "energy_oil_gas"
  | "power_utilities"
  | "metals_mining"
  | "cement_construction"
  | "industrials_capgoods"
  | "telecom"
  | "realestate_reits"
  | "consumer_retail"
  | "agri_chemicals"
  | "media_entertainment"
  | "default"

export const HERO_SECTOR_SLUGS: readonly HeroSectorSlug[] = [
  "banking",
  "nbfc",
  "insurance",
  "it_services",
  "fmcg",
  "auto",
  "pharma",
  "energy_oil_gas",
  "power_utilities",
  "metals_mining",
  "cement_construction",
  "industrials_capgoods",
  "telecom",
  "realestate_reits",
  "consumer_retail",
  "agri_chemicals",
  "media_entertainment",
  "default",
] as const

/**
 * Heuristic keyword match. First rule that hits wins; rules ordered
 * specificity-first so "PSU Bank" matches "banking" via "bank" before
 * the generic "PSU" / "Utility" rules.
 */
function classify(raw: string): HeroSectorSlug {
  const s = raw.toLowerCase()

  // Banking — Private Bank, PSU Bank, Banks, Bank Holding
  if (/\bbank/.test(s)) return "banking"
  // NBFC / asset management / capital markets / mortgage / fintech
  if (/nbfc|asset manag|capital market|mortgage|fintech|financial data/.test(s)) {
    return "nbfc"
  }
  // Insurance (incl. holding)
  if (/insur/.test(s)) return "insurance"
  // IT services / Internet / Healthcare IT / Healthcare BPM
  if (/it services|internet|healthcare it|healthcare bpm|services\b/.test(s)) {
    return "it_services"
  }
  // FMCG — covers all FMCG sub-variants
  if (/fmcg/.test(s)) return "fmcg"
  // Auto — Auto, Auto Ancillary, Auto Parts, Auto Holding, Bearings
  if (/\bauto\b|bearing|auto parts|auto ancillary|auto holding/.test(s)) {
    return "auto"
  }
  // Pharma / Healthcare / Hospitals / Diagnostics / Biotech / CRO
  if (/pharma|healthcare\b|hospital|diagnost|biotech|\bcro\b/.test(s)) {
    return "pharma"
  }
  // Energy — Oil & Gas, Oil Marketing, Oil Refining, City Gas, Gas Utility
  if (/oil|\bgas\b/.test(s)) return "energy_oil_gas"
  // Power / utilities / renewables — covers Power Transmission, Power Utility
  if (/power|utilit|renewable/.test(s)) return "power_utilities"
  // Metals & Mining — Metals, Mining, Steel Pipes, Industrial Gases
  if (/metal|mining|steel|industrial gas/.test(s)) return "metals_mining"
  // Cement / construction / building materials / infrastructure / paints / ceramics
  if (/cement|construct|building material|infrastructure|infra\b|paint|ceramic/.test(s)) {
    return "cement_construction"
  }
  // Industrials / capital goods / electronics / automation / defence /
  // logistics / ports / shipping / aviation / hotels
  if (
    /cap goods|capital goods|industrial|automation|defence|electronic|logistic|port|shipping|aviation|hotel/.test(s)
  ) {
    return "industrials_capgoods"
  }
  // Telecom
  if (/telecom/.test(s)) return "telecom"
  // Realty / REITs
  if (/realty|reit|real estate/.test(s)) return "realestate_reits"
  // Consumer retail / apparel / QSR / consumer durables / consumer disc / consumer cyc
  if (/retail|apparel|\bqsr\b|consumer/.test(s)) return "consumer_retail"
  // Agri / chemicals / fertilizer
  if (/agrochem|chemical|fertilizer/.test(s)) return "agri_chemicals"
  // Media
  if (/media|entertainment/.test(s)) return "media_entertainment"

  return "default"
}

/** Resolve a (possibly null) raw sector string to a slug guaranteed to
 *  have an on-disk photo asset. */
export function sectorToHeroSlug(sector: string | null | undefined): HeroSectorSlug {
  if (!sector || typeof sector !== "string") return "default"
  return classify(sector)
}

/** Resolve a raw sector to its public-served photo path. Returned path
 *  is always non-null and always points at an existing asset. */
export function sectorToHeroImagePath(sector: string | null | undefined): string {
  return `/hero-sectors/${sectorToHeroSlug(sector)}.webp`
}
