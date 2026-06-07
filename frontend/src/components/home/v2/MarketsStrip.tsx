"use client"
// Markets strip — sticky top row of indices + USD/INR.
// Data: /api/v1/market/pulse?include_macro=true
// Bloomberg/Koyfin-style compact monospace.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getMarketPulse } from "@/lib/api"
import { formatPct } from "@/lib/utils"

const PREFERRED_ORDER = [
  "NIFTY 50",
  "NIFTY BANK",
  "SENSEX",
  "NIFTY IT",
  "NIFTY AUTO",
]

// 2026-06-07: per-index drill-down. Operator caught the "Markets →" link
// sending users to /discover (random stock picks). Same root cause for
// the cells themselves — they rendered as static divs even though each
// index has its own dashboard page. Map index names to existing routes;
// fall back to a static cell when no dashboard exists yet (SENSEX, etc).
const INDEX_ROUTES: Record<string, string> = {
  "NIFTY 50": "/nifty50",
  "NIFTY BANK": "/nifty-bank",
  "NIFTY IT": "/nifty-it",
}

function indexHref(label: string): string | null {
  const upper = label.toUpperCase()
  for (const [key, href] of Object.entries(INDEX_ROUTES)) {
    if (upper.includes(key)) return href
  }
  return null
}

function Cell({
  label,
  value,
  pct,
  href,
}: {
  label: string
  value: string
  pct: number | null
  href?: string | null
}) {
  const up = pct !== null && pct >= 0
  const color =
    pct === null
      ? "text-caption"
      : up
        ? "text-green-600 dark:text-green-400"
        : "text-red-600 dark:text-red-400"
  const inner = (
    <>
      <span className="text-[9px] font-bold uppercase tracking-wider text-caption truncate">
        {label}
      </span>
      <div className="flex items-baseline gap-1.5">
        <span className="text-sm font-mono font-semibold text-ink">
          {value}
        </span>
        <span className={`text-[11px] font-mono ${color}`}>
          {pct === null ? "—" : formatPct(pct)}
        </span>
      </div>
    </>
  )
  const className =
    "flex flex-col items-start min-w-[110px] flex-shrink-0 px-3 py-1.5 border-r border-border last:border-r-0"
  if (href) {
    return (
      <Link href={href} className={`${className} hover:bg-bg/30 transition`}>
        {inner}
      </Link>
    )
  }
  return <div className={className}>{inner}</div>
}

function Skeleton() {
  return (
    <div className="flex overflow-x-auto bg-surface border-y border-border">
      {[...Array(6)].map((_, i) => (
        <div
          key={i}
          className="min-w-[110px] flex-shrink-0 px-3 py-2 border-r border-border last:border-r-0"
        >
          <div className="h-2 w-12 bg-border rounded animate-pulse mb-1.5" />
          <div className="h-3 w-16 bg-border rounded animate-pulse" />
        </div>
      ))}
    </div>
  )
}

export default function MarketsStrip() {
  const { data: pulse, isLoading } = useQuery({
    queryKey: ["markets-strip"],
    queryFn: () => getMarketPulse(true),
    staleTime: 60 * 1000,
    retry: 1,
  })

  if (isLoading) return <Skeleton />
  if (!pulse) return null

  const indices = [...(pulse.indices ?? [])].sort((a, b) => {
    const ai = PREFERRED_ORDER.findIndex(p => a.name.toUpperCase().includes(p))
    const bi = PREFERRED_ORDER.findIndex(p => b.name.toUpperCase().includes(p))
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi)
  })

  return (
    <div className="bg-surface border-y border-border overflow-x-auto sticky top-0 z-30 backdrop-blur supports-[backdrop-filter]:bg-surface/95">
      <div className="flex items-stretch min-w-max">
        {indices.map(idx => (
          <Cell
            key={idx.name}
            label={idx.name}
            value={idx.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
            pct={idx.change_pct ?? null}
            href={indexHref(idx.name)}
          />
        ))}
        {pulse.usd_inr != null && (
          <Cell
            label="USD/INR"
            value={`₹${pulse.usd_inr.toFixed(2)}`}
            pct={null}
          />
        )}
        {pulse.risk_free_pct != null && (
          <Cell
            label="India 10Y"
            value={`${pulse.risk_free_pct.toFixed(2)}%`}
            pct={null}
          />
        )}
        <Link
          href="/markets"
          className="flex items-center px-3 text-[11px] font-semibold text-brand hover:underline whitespace-nowrap"
        >
          Markets →
        </Link>
      </div>
    </div>
  )
}
