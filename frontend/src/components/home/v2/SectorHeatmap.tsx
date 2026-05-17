"use client"
// Sector heatmap — 13 canonical sectors as tiles, color by avg_score.
// Data: /api/v1/market/sectors → [{name, avg_score, pct_undervalued, trend}]
// Limitation: no market-cap weighting on this endpoint yet, so all tiles
// are equal-sized. Follow-up: backend /market/sectors could add a
// total_mcap_cr field so tiles can be sized proportionally (treemap layout).

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getSectorOverview } from "@/lib/api"
// Note: no dedicated /sectors/[slug] route exists yet, so we link to
// the screener page (which has the broadest filter UI). TODO: when a
// /sectors index lands, swap this back to sectorSlug-based deeplinks.

function colorFor(score: number): string {
  // Score range observed: 30-80. Map to a 5-bucket green→amber→red scale.
  // Higher score = greener (more aggregate undervaluation+quality).
  if (score >= 70) return "bg-green-600 text-white"
  if (score >= 60) return "bg-green-500/80 text-white"
  if (score >= 50) return "bg-amber-400/80 text-ink"
  if (score >= 40) return "bg-orange-500/80 text-white"
  return "bg-red-500/80 text-white"
}

function Skeleton() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
      {[...Array(13)].map((_, i) => (
        <div key={i} className="h-20 bg-border/60 rounded-lg animate-pulse" />
      ))}
    </div>
  )
}

export default function SectorHeatmap() {
  const { data, isLoading } = useQuery({
    queryKey: ["sector-overview-home"],
    queryFn: getSectorOverview,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
          Sector Heatmap
        </h2>
        <p className="text-[10px] text-caption">Color: aggregate score · Click to screen</p>
      </div>
      {isLoading || !data ? (
        <Skeleton />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
          {data.map(s => (
            <Link
              key={s.name}
              href={`/screener?sector=${encodeURIComponent(s.name)}`}
              className={`${colorFor(s.avg_score)} rounded-lg p-3 hover:opacity-90 transition flex flex-col justify-between min-h-[80px]`}
              title={`${s.name}: score ${s.avg_score.toFixed(0)} · ${s.pct_undervalued.toFixed(0)}% below fair value · trend ${s.trend}`}
            >
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider truncate">
                  {s.name}
                </p>
                <p className="text-[9px] opacity-80 mt-0.5">
                  {s.pct_undervalued.toFixed(0)}% below FV
                </p>
              </div>
              <p className="text-xl font-mono font-bold tabular-nums">
                {s.avg_score.toFixed(0)}
              </p>
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}
