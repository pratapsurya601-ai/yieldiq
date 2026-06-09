"use client"
// Markets strip — sticky top row of indices + FX + commodities.
// Data: /api/v1/market/pulse?include_macro=true
// Bloomberg/Koyfin-style compact monospace.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getMarketPulse } from "@/lib/api"
import { formatPct } from "@/lib/utils"

// Refresh cadence: 60s during NSE market hours, frozen after-hours.
// Computed at query time so a user who leaves the tab open from 15:25
// flips to "frozen" the moment markets close.
function isMarketHoursIST(): boolean {
  // IST is UTC+5:30 — convert by adding 330 minutes to the current
  // UTC clock. Using the offset directly avoids tz database lookups
  // and is correct for India (no DST since 1947).
  const now = new Date()
  const istMs = now.getTime() + (now.getTimezoneOffset() + 330) * 60 * 1000
  const ist = new Date(istMs)
  const day = ist.getUTCDay() // 0 = Sun, 6 = Sat
  if (day === 0 || day === 6) return false
  const hour = ist.getUTCHours()
  // NSE open 09:15-15:30 IST. Round outward to 09:00-16:00 so the
  // pre-open / post-close auctions still get fresh data.
  return hour >= 9 && hour < 16
}

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
    // 2026-06-09 — auto-refresh during NSE hours only. After-hours the
    // initial fetch resolves and freezes (no point hammering the API
    // when bhavcopy/yfinance themselves aren't updating).
    refetchInterval: () => (isMarketHoursIST() ? 60 * 1000 : false),
    refetchIntervalInBackground: false,
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
        {/*
          Commodity tiles (Gold / Silver / Crude). Added 2026-06-09 for
          daily-engagement. Gold and silver display in ₹/10g (server-
          converted from USD/oz so the tile stays formatting-only).
          Crude stays USD/bbl per spec. Each tile shows "—" if yfinance
          rate-limited the upstream fetch — never crashes the strip.
        */}
        <Cell
          label="GOLD"
          value={
            pulse.gold_inr_per_10g != null
              ? `₹${Math.round(pulse.gold_inr_per_10g).toLocaleString("en-IN")}/10g`
              : "—"
          }
          pct={pulse.gold_usd_change_pct ?? null}
        />
        <Cell
          label="SILVER"
          value={
            pulse.silver_inr_per_10g != null
              ? `₹${Math.round(pulse.silver_inr_per_10g).toLocaleString("en-IN")}/10g`
              : "—"
          }
          pct={pulse.silver_usd_change_pct ?? null}
        />
        <Cell
          label="CRUDE"
          value={
            pulse.crude_usd != null
              ? `$${pulse.crude_usd.toFixed(1)}/bbl`
              : "—"
          }
          pct={pulse.crude_usd_change_pct ?? null}
        />
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
