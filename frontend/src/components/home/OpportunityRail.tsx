"use client"
// TODO: swap to design tokens
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getYieldIQ50 } from "@/lib/api"

const MIN_RAIL_ITEMS = 2;

// Curated slice of YieldIQ 50 — Wide moat + MoS > 20%. Non-advisory framing:
// we describe the filter, never say "buy" or "recommended".
//
// EMPTY-STATE POLICY (2026-04 UX restoration):
// Previously this rail returned `null` when the filter matched 0 rows or
// when the upstream query errored — the entire section silently vanished
// from the homepage, which read as a layout glitch and hid the fact that
// we *do* have a Discover surface. We now always render a card. The data-
// side fix (refilling the YieldIQ 50 cache when the wide-moat shortlist
// runs dry) is owned by the Discover cron, NOT this component. This rail
// is the user-facing fallback only.
function FallbackCard({
  message,
  ctaHref,
  ctaLabel,
}: {
  message: string
  ctaHref?: string
  ctaLabel?: string
}) {
  return (
    <section>
      <div className="px-4 mb-2">
        <h2 className="font-display text-base md:text-lg font-bold text-ink leading-snug">
          Top wide-moat stocks
        </h2>
      </div>
      <div className="px-4">
        <div className="bg-bg rounded-2xl border border-border p-5">
          <p className="text-sm text-body">{message}</p>
          {ctaHref && ctaLabel && (
            <Link
              href={ctaHref}
              className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand"
            >
              {ctaLabel}
            </Link>
          )}
        </div>
      </div>
    </section>
  )
}

export default function OpportunityRail() {
  const { data, isLoading, isError } = useQuery({
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

  // Both the error path and the empty-shortlist path render the same
  // friendly fallback. Previously isError showed "Shortlist temporarily
  // unavailable" which leaked infra language to users and contradicted
  // the PR #110 empty-state policy. The rail's API failing and the rail
  // returning zero wide-moat names look identical from the user's POV —
  // both mean "no shortlist to show right now" — so the copy should
  // match. (See EMPTY-STATE POLICY comment above.)
  if (isError || count < MIN_RAIL_ITEMS) {
    return (
      <FallbackCard
        message="Daily shortlist refreshes overnight — check back tomorrow morning."
        ctaHref="/discover/screener"
        ctaLabel="Browse Screener →"
      />
    )
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
