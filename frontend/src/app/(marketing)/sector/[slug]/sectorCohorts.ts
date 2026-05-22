// Day-108c (2026-05-23) — frontend mirror of the backend Day-108c slug
// list (backend/services/sector_pages.py SECTOR_PAGE_SLUGS).
//
// Used by:
//   - sitemap.ts (for crawl)
//   - generateStaticParams (for static rendering)
//   - this route's not-found gate
//
// Keep in sync with the backend slug set when adding/removing a cohort.
export const SECTOR_PAGE_SLUGS = [
  "it-services",
  "fmcg",
  "auto",
  "capital-goods",
  "pharma",
  "utilities",
  "banking",
  "metals",
  "cyclical",
] as const

export type SectorSlug = (typeof SECTOR_PAGE_SLUGS)[number]

export const SECTOR_DISPLAY: Record<SectorSlug, string> = {
  "it-services": "IT Services",
  "fmcg": "FMCG",
  "auto": "Auto",
  "capital-goods": "Capital Goods",
  "pharma": "Pharma",
  "utilities": "Utilities",
  "banking": "Banking",
  "metals": "Metals & Mining",
  "cyclical": "Cyclical (Cement & Broad)",
}

export function isSectorSlug(s: string): s is SectorSlug {
  return (SECTOR_PAGE_SLUGS as readonly string[]).includes(s)
}
