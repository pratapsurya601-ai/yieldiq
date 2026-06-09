"use client"
// Sector cohort grid — /markets hub (2026-06-09).
//
// Reuses the existing /api/v1/public/sector-rotation endpoint (cached
// 30min server-side, no auth) which already returns per-cohort
// {slug, display_name, ticker_count, median_mos_pct, median_score}.
// This component is the lighter-weight presentation of that data
// for the Markets hub — no heatmap colors, no "top discounts" rail,
// just a tidy 3-column grid of tiles linking out to each /sector/{slug}
// landing page.
//
// SEBI watch: the only on-tile signal is the descriptive median MoS
// number plus the constituent count. No verbs like buy/sell, no
// superlatives. The CTA reads "Sector page →" — purely navigational.

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Mirrors the backend payload shape (backend/services/sector_rotation.py).
// We only consume the fields actually rendered here — extra fields the
// rotation endpoint emits (top_discounts, fv_to_price, etc.) are
// allowed through but unused.
type SectorRow = {
  slug: string
  display_name: string
  ticker_count: number
  median_mos_pct: number | null
  median_score: number | null
}

type RotationPayload = {
  sectors: SectorRow[]
  ranked_slugs: string[]
  computed_at: string
  universe_ticker_count: number
}

async function fetchRotation(): Promise<RotationPayload | null> {
  const res = await fetch(`${API_BASE}/api/v1/public/sector-rotation`, {
    // Browser cache 5min; server-side edge cache is 30min so we ride
    // on that for the bulk of the freshness. Don't refetch on focus —
    // sector aggregates move daily, not minute-to-minute.
    cache: "default",
  })
  if (!res.ok) return null
  return (await res.json()) as RotationPayload
}

function formatMos(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${n.toFixed(0)}%`
}

function mosClass(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "text-caption"
  if (n >= 5) return "text-green-700 dark:text-green-400"
  if (n <= -5) return "text-rose-700 dark:text-rose-400"
  return "text-blue-700 dark:text-blue-400"
}

function SectorTile({ row }: { row: SectorRow }) {
  return (
    <Link
      href={`/sector/${row.slug}`}
      className="block bg-bg dark:bg-surface border border-border rounded-xl p-4 hover:border-brand hover:shadow-sm transition"
      data-testid="sector-cohort-tile"
    >
      <div className="flex items-baseline justify-between gap-2 mb-2">
        <p className="font-semibold text-ink truncate">
          {row.display_name}
        </p>
        <p className="text-[10px] text-caption font-mono whitespace-nowrap">
          {row.ticker_count} stocks
        </p>
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider text-caption">
          Median MoS
        </span>
        <span
          className={`text-sm font-mono font-semibold tabular-nums ${mosClass(row.median_mos_pct)}`}
          data-testid="sector-cohort-mos"
        >
          {formatMos(row.median_mos_pct)}
        </span>
      </div>
      <p className="text-[11px] text-brand mt-3">Sector page →</p>
    </Link>
  )
}

function Skeleton() {
  return (
    <div
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="sector-cohort-skeleton"
    >
      {[...Array(6)].map((_, i) => (
        <div
          key={i}
          className="bg-bg dark:bg-surface border border-border rounded-xl p-4"
        >
          <div className="h-4 w-28 bg-border rounded animate-pulse mb-3" />
          <div className="h-3 w-20 bg-border rounded animate-pulse mb-2" />
          <div className="h-3 w-16 bg-border rounded animate-pulse" />
        </div>
      ))}
    </div>
  )
}

// SEBI-safe empty-state copy: descriptive, no action verbs, no advice.
function Empty() {
  return (
    <div
      className="bg-bg dark:bg-surface border border-border rounded-xl p-6 text-center"
      data-testid="sector-cohort-empty"
    >
      <p className="text-sm text-caption">
        Sector cohort medians refreshing. Browse the sector pages directly
        meanwhile.
      </p>
      <Link
        href="/sector"
        className="text-sm font-semibold text-brand hover:underline mt-3 inline-block"
      >
        All sectors →
      </Link>
    </div>
  )
}

export default function SectorCohortGrid() {
  const { data, isLoading } = useQuery({
    queryKey: ["markets-hub", "sector-rotation"],
    queryFn: fetchRotation,
    staleTime: 30 * 60 * 1000,   // 30min — matches backend edge cache
    refetchOnWindowFocus: false,
    retry: 1,
  })

  if (isLoading) return <Skeleton />
  if (!data || !data.sectors || data.sectors.length === 0) return <Empty />

  // Render sectors in the order the backend chose (ranked_slugs).
  // Keeps "most-discounted first" so the page opens with the cohorts
  // that have the largest current cohort-median MoS at the top.
  const bySlug = new Map(data.sectors.map(s => [s.slug, s]))
  const ordered = data.ranked_slugs
    .map(slug => bySlug.get(slug))
    .filter((s): s is SectorRow => s !== undefined)

  return (
    <div
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="sector-cohort-grid"
    >
      {ordered.map(row => (
        <SectorTile key={row.slug} row={row} />
      ))}
    </div>
  )
}
