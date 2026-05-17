"use client"
// Your Portfolio table — Ticker | Price | Today | FV | MoS | Holding Return
// Sortable, clickable rows → /analysis/[ticker]
// Data: /api/v1/portfolio/holdings-live

import Link from "next/link"
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { getHoldingsLive, type LiveHolding } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { ArrowUpDown, Plus } from "lucide-react"
import { formatPct } from "@/lib/utils"

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
  return (
    <div className="bg-surface border border-border rounded-2xl p-4">
      <div className="h-4 w-32 bg-border rounded animate-pulse mb-3" />
      {[...Array(4)].map((_, i) => (
        <div key={i} className="flex gap-2 py-1.5">
          {[...Array(6)].map((_, j) => (
            <div key={j} className="h-3 flex-1 bg-border rounded animate-pulse" />
          ))}
        </div>
      ))}
    </div>
  )
}

export default function PortfolioPanel() {
  const token = useAuthStore(s => s.token)
  const { data, isLoading } = useQuery({
    queryKey: ["holdings-live-home-v2"],
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
              <Th k="fair_value" label="FV" right />
              <Th k="mos_pct" label="MoS" right />
              <Th k="pnl_pct" label="Return" right />
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 8).map((h: LiveHolding) => (
              <tr
                key={h.ticker}
                className="border-b border-border last:border-b-0 hover:bg-bg/50 transition"
              >
                <td className="px-2 py-2">
                  <Link
                    href={`/analysis/${h.display_ticker}`}
                    className="text-xs font-semibold text-ink hover:text-brand"
                  >
                    {h.display_ticker}
                  </Link>
                </td>
                <td className="px-2 py-2 text-right">
                  <NumCell value={h.current_price} prefix="₹" />
                </td>
                <td className="px-2 py-2 text-right">
                  <NumCell value={h.day_change_pct} pct />
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
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
