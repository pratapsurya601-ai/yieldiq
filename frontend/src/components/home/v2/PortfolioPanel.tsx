"use client"
// Your Portfolio table — Ticker | Price | Today | FV | MoS | Holding Return
// Sortable, clickable rows → /analysis/[ticker]
// Data: /api/v1/portfolio/holdings-live

import Link from "next/link"
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { getHoldingsLive, getSparklines, type LiveHolding } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { ArrowUpDown, Plus } from "lucide-react"
import { formatPct } from "@/lib/utils"
import TickerAvatar from "@/components/common/TickerAvatar"
import { Sparkline } from "@/components/common/Sparkline"

// Mirrors MarketsStrip / WatchlistPanel — 5min refresh during NSE
// trading, idle after-hours. Daily closes don't move intraday.
function isMarketHoursIST(): boolean {
  const now = new Date()
  const istMs = now.getTime() + (now.getTimezoneOffset() + 330) * 60 * 1000
  const ist = new Date(istMs)
  const day = ist.getUTCDay()
  if (day === 0 || day === 6) return false
  const hour = ist.getUTCHours()
  return hour >= 9 && hour < 16
}

type SortKey = "ticker" | "current_price" | "day_change_pct" | "fair_value" | "mos_pct" | "pnl_pct"
type SortDir = "asc" | "desc"

function NumCell({
  value,
  pct,
  prefix = "",
  decimals = 2,
}: {
  value: number | null | undefined
  pct?: boolean
  prefix?: string
  decimals?: number
}) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return <span className="text-caption font-mono">—</span>
  }
  const color =
    pct === true
      ? value >= 0
        ? "text-green-600 dark:text-green-400"
        : "text-red-600 dark:text-red-400"
      : "text-ink"
  const display = pct ? formatPct(value) : `${prefix}${value.toFixed(decimals)}`
  return <span className={`font-mono text-xs ${color}`}>{display}</span>
}

function EmptyState() {
  return (
    <div className="bg-surface border border-border rounded-2xl p-6 text-center">
      <h3 className="text-sm font-semibold text-ink mb-1">Your Portfolio</h3>
      <p className="text-xs text-body mb-4">
        Add tickers to start tracking fair value, margin of safety, and PnL.
      </p>
      <Link
        href="/portfolio"
        className="inline-flex items-center gap-1.5 bg-brand text-white text-xs font-semibold px-3 py-1.5 rounded-lg hover:opacity-90 transition"
      >
        <Plus className="w-3.5 h-3.5" />
        Add holdings
      </Link>
    </div>
  )
}

function Skeleton() {
  // Day-28 (2026-05-20): skeleton now mirrors the actual table layout —
  // header row with title + P&L badge + "See all" link, then 6-column
  // table with 6 placeholder rows. Removes the layout shift when the
  // live holdings render. Uses bg-border pulse to stay consistent with
  // existing v2 panels.
  return (
    <div
      className="bg-surface border border-border rounded-2xl overflow-hidden"
      data-testid="portfolio-panel-loading-skeleton"
    >
      {/* Header band — title + P&L badge + See all link */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="space-y-1.5">
          <div className="h-4 w-32 bg-border rounded animate-pulse" />
          <div className="flex items-center gap-2">
            <div className="h-3 w-16 bg-border/70 rounded animate-pulse" />
            <div className="h-3 w-12 bg-border/70 rounded animate-pulse" />
          </div>
        </div>
        <div className="h-3 w-14 bg-border/70 rounded animate-pulse" />
      </div>
      {/* Table band — th row + 6 tr rows × 7 td cells (added 7d trend col 2026-06-09). */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-bg/50 border-b border-border">
            <tr>
              {[0, 1, 2, 3, 4, 5, 6].map((i) => (
                <th key={i} className="px-2 py-2">
                  <div className="h-3 w-12 bg-border rounded animate-pulse" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <tr key={row} className="border-b border-border last:border-b-0">
                {[0, 1, 2, 3, 4, 5, 6].map((col) => (
                  <td key={col} className="px-2 py-2.5">
                    <div
                      className={`h-3 ${col === 0 ? "w-14" : col === 3 ? "w-16 ml-auto" : "w-10 ml-auto"} bg-border/80 rounded animate-pulse`}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function PortfolioPanel() {
  const token = useAuthStore(s => s.token)
  // Canonical ["holdings-live"] key, shared with PortfolioQualityCard so
  // both panels resolve from a single /portfolio/holdings-live request.
  const { data, isLoading } = useQuery({
    queryKey: ["holdings-live"],
    queryFn: getHoldingsLive,
    enabled: !!token,
    staleTime: 60 * 1000,
    retry: 1,
  })

  const [sortKey, setSortKey] = useState<SortKey>("mos_pct")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const holdings = data?.holdings ?? []
  const sorted = useMemo(() => {
    const arr = [...holdings]
    arr.sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[sortKey]
      const bv = (b as unknown as Record<string, unknown>)[sortKey]
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av)
      }
      const an = typeof av === "number" ? av : -Infinity
      const bn = typeof bv === "number" ? bv : -Infinity
      return sortDir === "asc" ? an - bn : bn - an
    })
    return arr
  }, [holdings, sortKey, sortDir])

  // Batch sparkline fetch for the displayed holdings. Keyed by the
  // display_ticker set (sorted for stable cache key under re-sorts of
  // the table). One round-trip on mount, then 5min refresh during
  // market hours so the 7d trend stays in sync with the post-close
  // bhavcopy refresh without burning the API after-hours.
  const sparkTickers = sorted.slice(0, 8).map(h => h.display_ticker)
  const { data: sparkResp } = useQuery({
    queryKey: ["portfolio-sparklines", [...sparkTickers].sort().join(",")],
    queryFn: () => getSparklines(sparkTickers, "7d"),
    enabled: sparkTickers.length > 0,
    staleTime: 60 * 1000,
    refetchInterval: () => (isMarketHoursIST() ? 5 * 60 * 1000 : false),
    refetchIntervalInBackground: false,
    retry: 1,
  })
  const sparkSeries = sparkResp?.series ?? {}

  if (isLoading) return <Skeleton />
  if (holdings.length === 0) return <EmptyState />

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc")
    else { setSortKey(k); setSortDir("desc") }
  }

  function Th({ k, label, right = false }: { k: SortKey; label: string; right?: boolean }) {
    return (
      <th
        className={`px-2 py-2 text-[10px] font-bold uppercase tracking-wider text-caption cursor-pointer hover:text-ink whitespace-nowrap ${right ? "text-right" : "text-left"}`}
        onClick={() => toggleSort(k)}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          <ArrowUpDown className="w-2.5 h-2.5 opacity-60" />
        </span>
      </th>
    )
  }

  const summary = data?.summary
  const summaryPnl = summary?.total_pnl_pct ?? null

  return (
    <div className="bg-surface border border-border rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
          <h3 className="text-sm font-semibold text-ink">Your Portfolio</h3>
          {summary && (
            <p className="text-[11px] text-caption mt-0.5">
              {summary.count} positions
              {summaryPnl !== null && (
                <span className={`ml-2 font-mono ${summaryPnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {formatPct(summaryPnl)}
                </span>
              )}
            </p>
          )}
        </div>
        <Link href="/portfolio" className="text-xs font-semibold text-brand hover:underline">
          See all →
        </Link>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-bg/50 border-b border-border">
            <tr>
              <Th k="ticker" label="Ticker" />
              <Th k="current_price" label="Price" right />
              <Th k="day_change_pct" label="Today" right />
              {/* 7d trend column is non-sortable — it's a visual cue, not
                  a numeric key. Header uses the same tracking-wider
                  uppercase styling as the sortable Th's for visual
                  parity but no click handler. */}
              <th className="px-2 py-2 text-[10px] font-bold uppercase tracking-wider text-caption whitespace-nowrap text-right">
                7d
              </th>
              <Th k="fair_value" label="FV" right />
              <Th k="mos_pct" label="MoS" right />
              <Th k="pnl_pct" label="Return" right />
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 8).map((h: LiveHolding) => {
              const series = sparkSeries[h.display_ticker]
              // 7-day period change derived from the same series we plot.
              // Cheap to compute here (≤ 7 entries) and saves a second
              // network field. Null when the series is missing or
              // collapsed to a single point — UI hides the % then.
              let periodPct: number | null = null
              if (series && series.length >= 2 && series[0] > 0) {
                periodPct = ((series[series.length - 1] - series[0]) / series[0]) * 100
              }
              return (
                <tr
                  key={h.ticker}
                  className="border-b border-border last:border-b-0 hover:bg-bg/50 transition"
                >
                  <td className="px-2 py-2">
                    <Link
                      href={`/analysis/${h.display_ticker}`}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink hover:text-brand"
                    >
                      <TickerAvatar ticker={h.ticker} sector={h.sector} size="sm" />
                      <span>{h.display_ticker}</span>
                    </Link>
                  </td>
                  <td className="px-2 py-2 text-right">
                    <NumCell value={h.current_price} prefix="₹" />
                  </td>
                  <td className="px-2 py-2 text-right">
                    <NumCell value={h.day_change_pct} pct />
                  </td>
                  <td className="px-2 py-2 text-right">
                    {series && series.length >= 2 ? (
                      <div className="inline-flex items-center justify-end gap-1.5">
                        <Sparkline values={series} width={56} height={18} />
                        {periodPct !== null && (
                          <span
                            className={`font-mono text-[10px] tabular-nums ${
                              periodPct >= 0
                                ? "text-green-600 dark:text-green-400"
                                : "text-red-600 dark:text-red-400"
                            }`}
                          >
                            {periodPct >= 0 ? "+" : ""}
                            {periodPct.toFixed(1)}%
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-caption font-mono text-xs">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <NumCell value={h.fair_value} prefix="₹" />
                  </td>
                  <td className="px-2 py-2 text-right">
                    <NumCell value={h.mos_pct} pct />
                  </td>
                  <td className="px-2 py-2 text-right">
                    <NumCell value={h.pnl_pct} pct />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
