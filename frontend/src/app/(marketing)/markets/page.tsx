// Markets hub — Tickertape-style overview (2026-06-09 rewrite).
//
// Replaces the prior 90-LOC placeholder (3 static index links + 1
// "all sectors" CTA). The new layout reuses existing widgets:
//
//   1. Page hero — descriptive, tightened copy.
//   2. MarketsStrip (non-sticky) — live indices + macro tiles +
//      commodities. Same component /home uses; sticky disabled so
//      it doesn't visually conflict with the hub's own hero band.
//   3. Index dashboards row — three named dashboards (NIFTY 50,
//      NIFTY BANK, NIFTY IT), each enriched with the live level +
//      1d change % from the same /pulse call MarketsStrip uses.
//   4. Today's Movers — gainers + losers from the NIFTY 500.
//   5. Sector cohort grid — every Day-108c cohort with its current
//      median MoS + constituent count. Reuses the existing
//      /api/v1/public/sector-rotation endpoint.
//   6. Institutional flows (FII/DII) — when the macro service has
//      a recent row. Hidden entirely on empty.
//   7. Disclaimer.
//
// SEBI-safe throughout: descriptive language only. Action verbs and
// superlatives are absent. The model-output panels (movers, cohort
// medians) carry explicit "not advice" framing via the page-bottom
// disclaimer.
//
// Server-rendered shell + selective client islands for the live
// widgets (which depend on React-Query). The page itself stays a
// server component for SEO + initial bytes.

import type { Metadata } from "next"
import Link from "next/link"

import MarketsStrip from "@/components/home/v2/MarketsStrip"
import TodaysMovers from "@/components/home/v2/TodaysMovers"
import IndexDashboardsRow from "./IndexDashboardsRow"
import SectorCohortGrid from "./SectorCohortGrid"
import FlowsPanel from "./FlowsPanel"

export const metadata: Metadata = {
  title: "Markets — Indices, sectors, commodities | YieldIQ",
  description:
    "Indian indices, sector cohorts, and commodity panel at a glance. NIFTY 50, NIFTY BANK, NIFTY IT, top movers, sector median margin-of-safety, and institutional flows.",
  openGraph: {
    title: "Markets — Indices, sectors, commodities | YieldIQ",
    description:
      "Indian indices, sector cohorts, and commodity panel at a glance.",
    url: "https://yieldiq.in/markets",
    siteName: "YieldIQ",
    type: "website",
  },
  alternates: { canonical: "https://yieldiq.in/markets" },
}

export default function MarketsHubPage() {
  return (
    <div className="min-h-screen bg-bg dark:bg-surface">
      {/* Hero — tightened copy per spec. */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-12 sm:py-16">
        <div className="max-w-5xl mx-auto px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">
            Markets
          </h1>
          <p className="text-caption">
            Indian indices, sectors, commodities — at a glance.
          </p>
        </div>
      </section>

      {/* MarketsStrip — non-sticky on this page, and with the hub link
          suppressed because clicking "Markets →" while ON /markets is a
          self-reference (Bug 1, 2026-06-09). The strip itself is a
          client component that fetches /api/v1/market/pulse. */}
      <MarketsStrip sticky={false} showHubLink={false} />

      <div className="max-w-5xl mx-auto px-4 py-10 space-y-10">
        {/* Index dashboards — enriched with live level + 1d change. */}
        <section>
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink mb-4">
            Index dashboards
          </h2>
          <IndexDashboardsRow />
        </section>

        {/* Today's Movers — reuses /home component verbatim. */}
        <section>
          <TodaysMovers />
        </section>

        {/* Sector cohort grid — replaces the old single "Browse all
            sectors" link with a per-cohort tile carrying median MoS +
            constituent count. */}
        <section>
          <div className="flex items-baseline justify-between gap-3 mb-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
              Sector cohorts
            </h2>
            <Link
              href="/sector"
              className="text-xs font-semibold text-brand hover:underline"
            >
              All sectors →
            </Link>
          </div>
          <SectorCohortGrid />
        </section>

        {/* Institutional flows — FII + DII net for the most recent
            NSE day. Component returns null when data is missing so
            we don't render an empty header on the page. */}
        <FlowsPanel />

        <p className="text-[10px] text-caption text-center mt-10 max-w-2xl mx-auto">
          Index, sector, and flow data display model output and
          third-party feeds for educational and informational use. Not
          investment advice. YieldIQ is not a SEBI-registered investment
          adviser.
        </p>
      </div>
    </div>
  )
}
