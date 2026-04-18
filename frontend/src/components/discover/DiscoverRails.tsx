"use client"

import Link from "next/link"
import type { ScreenerStock } from "@/types/api"

// The three rails added in the /discover polish pass. Each rail composes
// existing YieldIQ 50 data so no new backend work is required. Sections
// that can't be powered from existing fields render a "Coming soon" stub
// rather than fabricating data — SEBI rules forbid fake "recommendations".

const TRACKED_SECTORS = ["Banking", "IT", "Pharma", "FMCG", "Auto", "Energy"] as const

// Normalise the free-text sector field from the backend into our canonical
// chip labels. Anything we can't classify is dropped from the rail.
function classifySector(raw: string | undefined | null): string | null {
  if (!raw) return null
  const s = raw.toLowerCase()
  if (s.includes("bank") || s.includes("financial")) return "Banking"
  if (s.includes("tech") || s.includes("software") || s.includes("it ") || s === "it") return "IT"
  if (s.includes("pharma") || s.includes("health") || s.includes("drug")) return "Pharma"
  if (s.includes("fmcg") || s.includes("consumer defensive") || s.includes("staple")) return "FMCG"
  if (s.includes("auto")) return "Auto"
  if (s.includes("energy") || s.includes("oil") || s.includes("gas") || s.includes("power") || s.includes("utilit")) return "Energy"
  return null
}

interface SectorLeadersProps {
  stocks: ScreenerStock[]
}

// Top ticker per tracked sector from YieldIQ 50 (already sorted by score
// descending by the backend). We walk the list once and claim the first
// hit for each bucket — O(n) and preserves the model's own ranking.
export function SectorLeaders({ stocks }: SectorLeadersProps) {
  const leaders = new Map<string, ScreenerStock>()
  for (const stock of stocks) {
    const bucket = classifySector(stock.sector)
    if (!bucket) continue
    if (!TRACKED_SECTORS.includes(bucket as typeof TRACKED_SECTORS[number])) continue
    if (!leaders.has(bucket)) leaders.set(bucket, stock)
  }
  type SectorName = typeof TRACKED_SECTORS[number]
  const items = TRACKED_SECTORS
    .map((sector) => ({ sector, stock: leaders.get(sector) }))
    .filter((x): x is { sector: SectorName; stock: ScreenerStock } => !!x.stock)

  if (items.length === 0) return null

  return (
    <section>
      <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">Sector leaders</p>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {items.map(({ sector, stock }) => (
          <Link
            key={sector}
            href={`/analysis/${stock.ticker}`}
            className="bg-white rounded-xl border border-gray-100 p-3 hover:border-blue-300 hover:shadow-sm active:scale-[0.98] transition"
          >
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-bold text-gray-900 truncate">{stock.ticker.replace(".NS", "")}</p>
              <span className="text-[9px] font-semibold text-gray-500 bg-gray-100 rounded px-1.5 py-0.5 uppercase tracking-wider">{sector}</span>
            </div>
            <p className="text-base font-bold text-blue-700 font-mono">
              {stock.margin_of_safety > 0 ? "+" : ""}
              {stock.margin_of_safety.toFixed(0)}%
            </p>
            <p className="text-[10px] text-gray-400">MoS &middot; Model estimate</p>
          </Link>
        ))}
      </div>
      <p className="text-[10px] text-gray-500 mt-1">Highest-scoring stock in each sector from YieldIQ 50. Not investment advice.</p>
    </section>
  )
}

// 52-week lows rail. The public ScreenerStock shape doesn't include a
// 52W high/low marker yet, so we can't identify "near lows" without
// fabricating data. Render a factual placeholder until the endpoint
// ships — never invent MoS or low distance values here.
export function NearLowsRail() {
  return (
    <section>
      <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">52-week lows with strong fundamentals</p>
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="bg-white rounded-xl border border-dashed border-gray-200 p-4 min-h-[96px] text-center flex flex-col items-center justify-center">
            <div className="skeleton h-3 w-16 rounded mb-2" />
            <div className="skeleton h-4 w-12 rounded" />
          </div>
        ))}
      </div>
      <p className="text-[10px] text-gray-500 mt-1">Coming soon &mdash; 52-week low data not yet exposed. Model estimate.</p>
    </section>
  )
}

interface LowestPERailProps {
  stocks: ScreenerStock[]
}

// Lowest P/E in YieldIQ 50. The ScreenerStock type has no `pe_ratio` /
// `ev_ebitda` field (see types/api.ts — it's on PeerRow, not on the
// screener response), so we can't sort without fabrication. Stub it.
export function LowestPERail({ stocks }: LowestPERailProps) {
  // Intentionally unused — keeping the prop so a future backend patch that
  // adds pe_ratio to ScreenerResponse only needs to flip this component on.
  void stocks
  return (
    <section>
      <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">Lowest P/E in YieldIQ 50</p>
      <div className="bg-white rounded-xl border border-dashed border-gray-200 p-6 text-center">
        <p className="text-sm font-semibold text-gray-700 mb-1">Coming soon</p>
        <p className="text-xs text-gray-500 max-w-xs mx-auto">P/E multiples aren&rsquo;t in the YieldIQ 50 response yet. We&rsquo;ll light this rail up once the field ships. Model estimate.</p>
      </div>
    </section>
  )
}
