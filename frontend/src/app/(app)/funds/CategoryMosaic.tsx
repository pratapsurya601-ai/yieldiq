"use client"
/**
 * CategoryMosaic — the animated centerpiece of the /funds hub.
 *
 * A responsive tile grid built from the true category census
 * (/api/v1/funds/categories → { category, count }). Each tile is a
 * <Link> into the filtered view (`/funds?category=<raw>`), so selecting
 * a category is a normal navigation — the server page re-renders the
 * filtered card grid. No client filter state lives here; the hub stays
 * static-ISR friendly.
 *
 * The first / largest tile spans two columns on lg as a visual anchor.
 * Tiles cascade in via RevealStagger (threshold={0} so the grid, which
 * can exceed 15% of the viewport, is never stuck at opacity-0 — memory
 * #939). Each count animates with NumberFlip on entry.
 *
 * If there are more than 12 categories, the first 12 render plus an
 * "All categories" expander that reveals the remainder with an animated
 * height transition.
 *
 * SEBI: category labels are raw AMFI/SEBI-published strings — factual.
 * Tile tints are decorative; no advisory meaning, no ranking claim.
 */
import { useState } from "react"
import Link from "next/link"

import { NumberFlip, RevealStagger } from "@/components/motion"
import { compactCategory } from "./FundCard"

export interface MosaicCategory {
  /** Raw AMFI category string (the API filter value). */
  category: string
  /** True COUNT(*) of active schemes in this category. */
  count: number
}

const INITIAL_VISIBLE = 12

function CategoryTile({
  cat,
  featured,
}: {
  cat: MosaicCategory
  featured: boolean
}) {
  const label = compactCategory(cat.category) || cat.category
  return (
    <Link
      href={`/funds?category=${encodeURIComponent(cat.category)}`}
      className={`group flex h-full flex-col justify-between rounded-xl border border-border bg-surface p-4 transition-colors duration-200 hover:-translate-y-0.5 hover:border-ink/20 hover:bg-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
        featured ? "lg:col-span-2" : ""
      }`}
      style={{ transition: "transform 200ms ease, background-color 200ms ease, border-color 200ms ease" }}
    >
      <div
        className={`font-semibold leading-snug text-ink group-hover:text-brand ${
          featured ? "text-base" : "text-sm"
        }`}
      >
        {label}
      </div>
      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-lg font-semibold text-ink num">
          <NumberFlip value={cat.count} duration={0.9} />
        </span>
        <span className="text-[11px] text-caption">
          {cat.count === 1 ? "scheme" : "schemes"}
        </span>
      </div>
    </Link>
  )
}

export default function CategoryMosaic({
  categories,
}: {
  categories: MosaicCategory[]
}) {
  const [expanded, setExpanded] = useState(false)

  if (categories.length === 0) return null

  const hasOverflow = categories.length > INITIAL_VISIBLE
  const visible =
    hasOverflow && !expanded ? categories.slice(0, INITIAL_VISIBLE) : categories

  return (
    <section className="space-y-3">
      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase leading-4 tracking-[0.06em] text-caption">
          Browse
        </p>
        <h2 className="text-[22px] font-semibold leading-7 tracking-tight text-ink">
          Fund categories
        </h2>
      </div>

      <RevealStagger
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
        staggerMs={50}
        direction="up"
        threshold={0}
      >
        {visible.map((cat, i) => (
          <CategoryTile key={cat.category} cat={cat} featured={i === 0} />
        ))}
      </RevealStagger>

      {hasOverflow ? (
        <div className="pt-1">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="rounded-full border border-border bg-raised px-4 py-2 text-[12px] font-medium text-body transition-colors hover:bg-surface hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {expanded
              ? "Show fewer categories"
              : `All categories (${categories.length})`}
          </button>
        </div>
      ) : null}
    </section>
  )
}
