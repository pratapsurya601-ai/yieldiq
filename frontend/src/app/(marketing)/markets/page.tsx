// Markets hub — 2026-06-07.
//
// Operator caught the MarketsStrip "Markets →" link sending users to
// /discover (which shows random stock picks) instead of a markets-
// overview surface. Three index dashboards already exist (`/nifty50`,
// `/nifty-bank`, `/nifty-it`) plus the sector hub at `/sector`. This
// page is a minimal honest aggregator: lists the index dashboards and
// links to the sector hub, no live data of its own.
//
// Future build: full Tickertape-style markets page with sector heatmap,
// top gainers/losers, FII/DII flows, USD/INR + India 10Y panel. Today
// this page just provides a non-misleading destination so the strip's
// "Markets →" link doesn't lie about what's behind it.
//
// Static. No API calls. SEBI-lint clean — descriptive copy only.

import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = {
  title: "Markets — Indian Indices & Sectors | YieldIQ",
  description:
    "Browse NIFTY 50, NIFTY BANK, NIFTY IT, and all sector cohorts tracked by YieldIQ. Each index dashboard shows constituents, performance, and the cohort median valuation lens.",
}

interface IndexEntry {
  href: string
  name: string
  description: string
}

const INDEX_DASHBOARDS: IndexEntry[] = [
  {
    href: "/nifty50",
    name: "NIFTY 50",
    description:
      "The 50 largest NSE-listed companies by free-float market cap. Sector breakdown, constituent table, and cohort median valuation lens.",
  },
  {
    href: "/nifty-bank",
    name: "NIFTY BANK",
    description:
      "The 12-stock NIFTY Bank index — public-sector and private-sector banks side by side. P/B and residual-income lens (banks don't use DCF).",
  },
  {
    href: "/nifty-it",
    name: "NIFTY IT",
    description:
      "The Indian IT services cohort — TCS, Infosys, Wipro, HCLTech, and second-tier exporters. Tier-1 vs Tier-2 segmentation built in.",
  },
]

export default function MarketsHubPage() {
  return (
    <div className="min-h-screen bg-bg dark:bg-surface">
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12 sm:py-16">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">
            Markets
          </h1>
          <p className="text-caption">
            Indian indices and sector cohorts tracked by YieldIQ.
          </p>
        </div>
      </section>

      <section className="max-w-4xl mx-auto px-4 py-10">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink mb-4">
          Index dashboards
        </h2>
        <div className="grid sm:grid-cols-2 gap-3">
          {INDEX_DASHBOARDS.map(idx => (
            <Link
              key={idx.href}
              href={idx.href}
              className="block bg-bg dark:bg-surface border border-border rounded-xl p-5 hover:border-blue-300 hover:shadow-sm transition"
            >
              <p className="text-base font-bold text-ink mb-1">{idx.name}</p>
              <p className="text-xs text-caption">{idx.description}</p>
            </Link>
          ))}
        </div>

        <h2 className="text-sm font-bold uppercase tracking-wider text-ink mt-12 mb-4">
          Sector cohorts
        </h2>
        <Link
          href="/sector"
          className="block bg-bg dark:bg-surface border border-border rounded-xl p-5 hover:border-blue-300 hover:shadow-sm transition"
        >
          <p className="text-base font-bold text-ink mb-1">
            Browse all sectors →
          </p>
          <p className="text-xs text-caption">
            IT services, FMCG, auto, capital goods, pharma, utilities,
            banking, metals, cyclical. Each sector page shows the cohort
            median score, margin of safety, and a sortable constituent table.
          </p>
        </Link>

        <p className="text-[10px] text-caption text-center mt-10 max-w-xl mx-auto">
          Index and sector pages display model output for educational and
          informational use. Not investment advice. YieldIQ is not a
          SEBI-registered investment adviser.
        </p>
      </section>
    </div>
  )
}
