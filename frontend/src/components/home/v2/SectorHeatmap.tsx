"use client"
// Sector heatmap — 13 canonical sectors as tiles, color by avg_score.
// Data: /api/v1/market/sectors → [{name, avg_score, pct_undervalued, trend}]
// Limitation: no market-cap weighting on this endpoint yet, so all tiles
// are equal-sized. Follow-up: backend /market/sectors could add a
// total_mcap_cr field so tiles can be sized proportionally (treemap layout).
//
// 2026-06-11 (P0 fix — "stuck on loading skeleton"): the previous
// render path bailed to <Skeleton /> on BOTH (isLoading) AND (!data).
// When /api/v1/market/sectors errored, react-query surfaced
// data=undefined and the skeleton animated forever — no empty-state
// copy, no retry handle, no escape hatch. The render path now treats
// (errored | empty | loading-too-long) as three distinct states and
// each gets dedicated copy. A 5s loading-timeout swap-out guarantees
// the user never sees the pulsing gray bars beyond a single beat.

import { useEffect, useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getSectorOverview } from "@/lib/api"
import ShimmerSkeleton from "@/components/motion/ShimmerSkeleton"
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
    <div
      className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2"
      data-testid="sector-heatmap-skeleton"
    >
      {[...Array(13)].map((_, i) => (
        <ShimmerSkeleton
          key={i}
          variant="block"
          className="h-20 rounded-lg"
          label="Loading sector"
        />
      ))}
    </div>
  )
}

function EmptyState({ onRetry }: { onRetry: () => void }) {
  // Compact single-tile fallback when the endpoint returned empty,
  // errored out, or didn't resolve within the 5s timeout. Keeps the
  // section heading consistent so the layout doesn't jump; the body
  // is replaced by a tile-shaped pane that explains the state and
  // offers a retry. Never let the skeleton animate forever — that's
  // the bug this fallback exists to close.
  return (
    <div
      className="bg-surface border border-border rounded-lg p-4 flex items-center justify-between gap-3 min-h-[80px]"
      data-testid="sector-heatmap-empty"
    >
      <div>
        <p className="text-xs font-semibold text-ink">
          Heatmap data unavailable
        </p>
        <p className="text-[11px] text-caption mt-0.5">
          The sector aggregator is refreshing. Try again in a moment.
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="text-xs font-semibold text-brand hover:underline whitespace-nowrap"
        data-testid="sector-heatmap-retry"
      >
        Retry →
      </button>
    </div>
  )
}

export default function SectorHeatmap() {
  // 2026-06-11 — retry bumped from 1 to 2 with exponential backoff
  // (1s → 2s) so a transient backend blip heals before the user sees
  // the EmptyState. Two retries is the sweet spot here: more than that
  // and we hang the panel during a real outage; less and we surface
  // the error too eagerly on a perfectly recoverable blip.
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["sector-overview-home"],
    queryFn: getSectorOverview,
    staleTime: 15 * 60 * 1000,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * Math.pow(2, attempt), 4000),
  })

  // 5s loading-timeout. Closes the "skeleton-animates-forever" P0
  // bug: a slow or hung endpoint leaves react-query in isLoading
  // indefinitely and the previous render path had no escape. After
  // 5s of nothing, we swap from <Skeleton /> to <EmptyState /> so
  // the user has a clear "Heatmap data unavailable" + Retry handle
  // instead of pulsing gray bars. The timeout resets every render
  // so a fast successful response still skips straight to the
  // populated grid.
  const [loadingTooLong, setLoadingTooLong] = useState(false)
  useEffect(() => {
    if (!isLoading) {
      setLoadingTooLong(false)
      return
    }
    const id = setTimeout(() => setLoadingTooLong(true), 5_000)
    return () => clearTimeout(id)
  }, [isLoading])

  // Resolve which render mode we're in. Order matters:
  //   1. errored      → EmptyState (highest signal — the fetch failed)
  //   2. loaded+empty → EmptyState (data array is [])
  //   3. loaded+ok    → the populated grid
  //   4. loading slow → EmptyState (after the 5s timeout)
  //   5. loading      → Skeleton
  const showEmpty =
    isError ||
    (!isLoading && (!data || data.length === 0)) ||
    (isLoading && loadingTooLong)

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
          Sector Heatmap
        </h2>
        <p className="text-[10px] text-caption">Color: aggregate score · Click to screen</p>
      </div>
      {showEmpty ? (
        <EmptyState onRetry={() => refetch()} />
      ) : !data ? (
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
