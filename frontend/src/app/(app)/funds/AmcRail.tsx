"use client"
/**
 * AmcRail — a horizontal, snap-scrolling row of fund-house chips.
 *
 * Built from the sampled scheme list: AMCs are counted and ordered by
 * how many of their schemes appear on the page — a factual, count-based
 * sort with no ranking claim. Each chip is a <Link> into the funds
 * search filtered to that house (`/funds?q=<amc>`), which the existing
 * list endpoint matches on amc ILIKE.
 *
 * AMC name is always present on every scheme, so this rail fills at
 * scale and never blanks. Chips reveal via RevealStagger (threshold={0})
 * and the row scrolls horizontally with CSS scroll-snap on small
 * viewports, wrapping on large ones.
 *
 * SEBI: descriptive. AmcAvatar + house name are facts; no advisory copy.
 */
import Link from "next/link"

import AmcAvatar from "@/components/common/AmcAvatar"
import { RevealStagger } from "@/components/motion"

export interface AmcFacet {
  amc: string
  count: number
}

export default function AmcRail({ amcs }: { amcs: AmcFacet[] }) {
  if (amcs.length === 0) return null

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase leading-4 tracking-[0.06em] text-caption">
            Fund houses
          </p>
          <h2 className="text-[22px] font-semibold leading-7 tracking-tight text-ink">
            Featured fund houses
          </h2>
        </div>
        <span className="shrink-0 text-[11px] text-caption">
          Most schemes on this page
        </span>
      </div>

      <RevealStagger
        className="flex snap-x gap-2 overflow-x-auto pb-1 lg:flex-wrap lg:overflow-visible"
        staggerMs={40}
        threshold={0}
      >
        {amcs.map((a) => (
          <Link
            key={a.amc}
            href={`/funds?q=${encodeURIComponent(a.amc)}`}
            className="flex h-9 shrink-0 snap-start items-center gap-2 rounded-full border border-border bg-raised px-3 text-[12px] font-medium text-body transition-colors hover:border-ink/20 hover:bg-surface hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <AmcAvatar amc={a.amc} size="sm" />
            <span className="max-w-[14rem] truncate">{a.amc}</span>
            <span className="text-[11px] text-caption num">{a.count}</span>
          </Link>
        ))}
      </RevealStagger>
    </section>
  )
}
