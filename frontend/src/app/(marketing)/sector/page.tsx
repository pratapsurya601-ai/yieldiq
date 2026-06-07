// J-copy-2b (audit item 17, 2026-05-26 cold-read audit) — sector
// index page at `/sector`. The 2026-05-26 audit found that the 9 sector
// landing pages (`/sector/<slug>`) had no discovery path from the
// marketing surface — a cold visitor had to type the slug or follow
// a sitemap link. This page lists all sectors with display names and
// brief one-line descriptions and is linked from the TrustFooter
// "Product" column.
//
// Static. No API calls. The slug list is the same one
// `[slug]/sectorCohorts.ts` exports and uses for generateStaticParams.
import type { Metadata } from "next"
import Link from "next/link"
import {
  SECTOR_PAGE_SLUGS,
  SECTOR_DISPLAY,
  type SectorSlug,
} from "./[slug]/sectorCohorts"

export const metadata: Metadata = {
  title: "Sectors | YieldIQ",
  description:
    "Browse all sector cohorts tracked by YieldIQ — IT services, FMCG, auto, capital goods, pharma, utilities, banking, metals, and cyclical. Each page shows the cohort median scores, margin of safety, and a sortable table of constituents.",
}

// One-line, descriptive blurbs. Strictly factual — no superlatives,
// no recommendations. SEBI banned-vocab clean.
const SECTOR_BLURBS: Record<SectorSlug, string> = {
  "it-services": "Indian IT services — TCS, Infosys, Wipro, HCLTech and the second-tier exporters.",
  "fmcg": "Fast-moving consumer goods — staples and discretionary household brands.",
  "auto": "Auto OEMs and component makers — two-wheelers, passenger vehicles, commercial vehicles.",
  "capital-goods": "Industrial capital equipment, EPC, and infrastructure exposure.",
  "pharma": "Domestic formulations + US generics + API exporters.",
  "utilities": "Power generation, transmission, and integrated utilities.",
  "banking": "Private and public-sector banks — deposit franchises and lending mix.",
  "metals": "Ferrous, non-ferrous and mining — commodity-cycle exposed.",
  "cyclical": "Cement and broader cyclical names that move with the capex cycle.",
}

export default function SectorIndexPage() {
  return (
    <main className="max-w-4xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
      <header className="mb-8">
        <p className="text-[11px] font-bold text-caption uppercase tracking-widest mb-2">
          Browse by sector
        </p>
        <h1 className="font-display text-3xl sm:text-4xl font-black text-ink tracking-tight mb-3">
          Sector cohorts
        </h1>
        <p className="text-body text-base max-w-2xl leading-relaxed">
          Each sector page shows the cohort median score, median margin
          of safety, and a sortable table of constituents. Sort order is
          purely numerical.
        </p>
        <p className="text-sm mt-4">
          <Link
            href="/sector-rotation"
            className="text-blue-700 dark:text-blue-400 hover:underline"
          >
            See the cross-sector rotation lens →
          </Link>
        </p>
      </header>

      <ul className="grid gap-3 sm:grid-cols-2">
        {SECTOR_PAGE_SLUGS.map(slug => (
          <li key={slug}>
            <Link
              href={`/sector/${slug}`}
              className="block bg-bg dark:bg-surface border border-border rounded-xl p-4 hover:border-brand hover:shadow-sm transition"
            >
              <p className="font-semibold text-ink mb-1">
                {SECTOR_DISPLAY[slug]}
              </p>
              <p className="text-sm text-caption leading-relaxed">
                {SECTOR_BLURBS[slug]}
              </p>
            </Link>
          </li>
        ))}
      </ul>

      <p className="text-xs text-caption mt-8 max-w-2xl leading-relaxed">
        Cohort membership and aggregates are recomputed nightly. Median
        figures exclude tickers without a current YieldIQ score. Not
        investment advice.
      </p>
    </main>
  )
}
