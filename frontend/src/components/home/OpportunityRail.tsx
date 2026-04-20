"use client"
// TODO: swap to design tokens
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getYieldIQ50 } from "@/lib/api"

// Curated slice of YieldIQ 50 — Wide moat + MoS > 20%. Non-advisory framing:
// we describe the filter, never say "buy" or "recommended".
export default function OpportunityRail() {
  const { data, isLoading } = useQuery({
    queryKey: ["yieldiq-50-home"],
    queryFn: getYieldIQ50,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  const all = data?.results ?? []
  const filtered = all.filter(
    (s) => (s.moat || "").toLowerCase() === "wide" && (s.margin_of_safety ?? 0) > 20,
  )
  const top = filtered.slice(0, 4)
  const count = filtered.length

  if (isLoading) {
    return (
      <section className="px-4">
        <div className="h-40 rounded-2xl bg-surface animate-pulse" />
      </section>
    )
  }

  if (count === 0) {
    // Don't fabricate a count. Hide the section cleanly if nothing qualifies.
    return null
  }

  return (
    <section>
      <div className="px-4 mb-2">
        <h2 className="font-display text-base md:text-lg font-bold text-ink leading-snug">
          {`${count} wide-moat ${count === 1 ? "stock" : "stocks"} now at >20% margin of safety`}
        </h2>
        <p className="text-xs text-caption mt-0.5">
          Filtered from the YieldIQ 50. Model estimate. Not investment advice.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2 px-4">
        {top.map((s) => (
          <Link
            key={s.ticker}
            href={`/analysis/${s.ticker}`}
            className="bg-surface rounded-xl border border-border p-3 hover:border-brand transition"
          >
            <div className="flex items-baseline justify-between gap-2">
              <p className="font-bold text-sm text-ink truncate">{s.ticker}</p>
              <p className="text-xs font-mono text-green-600 font-bold">
                {s.margin_of_safety != null ? `${s.margin_of_safety.toFixed(0)}% MoS` : "\u2014"}
              </p>
            </div>
            <p className="text-[11px] text-caption truncate">{s.company_name}</p>
            <p className="text-[10px] text-caption mt-1">
              Score {Math.round(s.score)} · {s.sector}
            </p>
          </Link>
        ))}
      </div>
      <div className="px-4 mt-3">
        <Link
          href="/discover"
          className="inline-flex items-center gap-1 text-sm font-semibold text-brand"
        >
          See all →
        </Link>
      </div>
    </section>
  )
}
