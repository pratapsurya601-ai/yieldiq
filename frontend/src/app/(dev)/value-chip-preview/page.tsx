import { notFound } from "next/navigation"

import { ValueBandChip, type ValueBand } from "@/components/hex/ValueBandChip"

// Dev-only fixture page. Hidden in production: returning notFound()
// renders the standard 404 so the route is invisible outside `next dev`.
export const dynamic = "force-dynamic"

interface Fixture {
  band: ValueBand
  label: string
  percentile?: number | null
  why?: string
  sectorPeers?: number
  sectorLabel?: string
}

const FIXTURES: Fixture[] = [
  {
    band: "strong_discount",
    label: "Deep discount",
    percentile: 8,
    why: "Trades at a notable discount vs. sector peers.",
    sectorPeers: 42,
    sectorLabel: "Information Technology",
  },
  {
    band: "below_peers",
    label: "Below peers",
    percentile: 28,
    why: "Lower multiples than most sector peers on blended ratios.",
    sectorPeers: 42,
    sectorLabel: "Information Technology",
  },
  {
    band: "in_range",
    label: "In range",
    percentile: 52,
    why: "Within the typical sector valuation range.",
    sectorPeers: 42,
    sectorLabel: "Information Technology",
  },
  {
    band: "above_peers",
    label: "Above peers",
    percentile: 74,
    why: "Higher multiples than most sector peers on blended ratios.",
    sectorPeers: 42,
    sectorLabel: "Information Technology",
  },
  {
    band: "notably_overvalued",
    label: "Notable premium to peers",
    percentile: 94,
    why: "Trades at a notable premium vs. sector peers.",
    sectorPeers: 42,
    sectorLabel: "Information Technology",
  },
  {
    band: "data_limited",
    label: "Data limited",
    percentile: null,
    why: "Insufficient sector peer coverage for a confident band.",
    sectorPeers: 3,
    sectorLabel: "Specialty Chemicals",
  },
]

export default function ValueChipPreviewPage() {
  if (process.env.NODE_ENV !== "development") {
    notFound()
  }

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">ValueBandChip preview</h1>
        <p className="text-sm text-gray-500">
          Dev-only fixture for visual review. Stage 1 of 2 — not wired
          into Hex yet.
        </p>
      </header>

      <section className="space-y-3">
        {FIXTURES.map((f) => (
          <div
            key={f.band}
            className="flex items-center gap-4 rounded-lg border border-gray-200 p-3"
          >
            <code className="text-xs text-gray-500 w-44 shrink-0">
              {f.band}
            </code>
            <ValueBandChip {...f} />
          </div>
        ))}
      </section>
    </main>
  )
}
