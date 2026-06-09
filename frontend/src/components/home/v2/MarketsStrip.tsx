"use client"
// Markets strip — sticky top row of indices + FX + commodities.
// Data: /api/v1/market/pulse?include_macro=true
// Bloomberg/Koyfin-style compact monospace.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getMarketPulse } from "@/lib/api"
import { Sparkline } from "@/components/common/Sparkline"
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
// fall back to a static cell when no dashboard exists yet.
// 2026-06-09: SENSEX wired to its own /sensex dashboard (Bug 3) — see
// `frontend/src/app/(marketing)/sensex/page.tsx`.
const INDEX_ROUTES: Record<string, string> = {
  "NIFTY 50": "/nifty50",
  "NIFTY BANK": "/nifty-bank",
  "NIFTY IT": "/nifty-it",
  "SENSEX": "/sensex",
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
  sparkline,
}: {
  label: string
  value: string
  pct: number | null
  href?: string | null
  /**
   * 7 daily closes oldest→newest. Optional — when undefined or
   * empty, the sparkline row collapses and the tile keeps its
   * pre-PR vertical rhythm (no empty white gap).
   */
  sparkline?: number[]
}) {
  const up = pct !== null && pct >= 0
  const color =
    pct === null
      ? "text-caption"
      : up
        ? "text-green-600 dark:text-green-400"
        : "text-red-600 dark:text-red-400"
  // Force the sparkline color to match the % change badge above it
  // (green when up, red when down, neutral when flat) so the two
  // signals never visually disagree mid-render. When the badge is
  // null (USD/INR with no delta available), let the sparkline
  // derive its own color from the series direction.
  const sparkColor: "green" | "red" | "neutral" | undefined =
    pct === null ? undefined : up ? "green" : "red"
  const hasSpark = Array.isArray(sparkline) && sparkline.length >= 2
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
      {hasSpark && (
        <div className="mt-0.5">
          <Sparkline
            values={sparkline as number[]}
            width={64}
            height={16}
            color={sparkColor}
          />
        </div>
      )}
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

/**
 * MarketsStrip props.
 *
 * sticky: when true (default, preserves /home behavior) the strip pins
 * to the top of the viewport with `sticky top-0 z-30`. The /markets
 * hub page passes sticky={false} because the page already has its
 * own hero band — letting the strip stick a second time creates a
 * visual double-band and conflicts with the page-level scroll layer.
 *
 * showHubLink: when true (default), the strip terminates with a
 * "Markets →" link pointing at /markets. When the strip is mounted on
 * /markets itself, that link is a self-reference and the page passes
 * showHubLink={false} to omit it. Default behavior is preserved so the
 * /home snapshot stays byte-identical (Bug 1, 2026-06-09).
 */
export interface MarketsStripProps {
  sticky?: boolean
  showHubLink?: boolean
}

export default function MarketsStrip({
  sticky = true,
  showHubLink = true,
}: MarketsStripProps = {}) {
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

  // Macro tiles (USD/INR, GOLD, SILVER, CRUDE, INDIA10Y) read their
  // sparkline series out of pulse.macro_sparklines when present.
  // Fallback to undefined → tile renders without a sparkline cell.
  const macro = pulse.macro_sparklines ?? undefined
  function macroSpark(key: string): number[] | undefined {
    if (!macro) return undefined
    const v = macro[key]
    return Array.isArray(v) && v.length >= 2 ? v : undefined
  }

  // Sticky-mode classes preserved verbatim so the existing /home
  // surface (and its snapshot test) is byte-identical. Only the
  // /markets hub passes sticky={false}.
  const wrapperClass = sticky
    ? "bg-surface border-y border-border overflow-x-auto sticky top-0 z-30 backdrop-blur supports-[backdrop-filter]:bg-surface/95"
    : "bg-surface border-y border-border overflow-x-auto"
  return (
    <div className={wrapperClass}>
      <div className="flex items-stretch min-w-max">
        {indices.map(idx => (
          <Cell
            key={idx.name}
            label={idx.name}
            value={idx.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
            pct={idx.change_pct ?? null}
            href={indexHref(idx.name)}
            sparkline={idx.sparkline_7d}
          />
        ))}
        {pulse.usd_inr != null && (
          <Cell
            label="USD/INR"
            value={`₹${pulse.usd_inr.toFixed(2)}`}
            // 2026-06-09 — was hardcoded null pre-fix. Backend now
            // derives the 24h delta from the same cached yfinance
            // series that backs macro_sparklines.USDINR. Null still
            // means "yfinance unavailable" and the tile shows "—".
            pct={pulse.usd_inr_change_pct ?? null}
            sparkline={macroSpark("USDINR")}
          />
        )}
        {pulse.risk_free_pct != null && (
          <Cell
            label="India 10Y"
            value={`${pulse.risk_free_pct.toFixed(2)}%`}
            // 2026-06-09 — was hardcoded null pre-fix. Backend now
            // derives the 24h delta from the yfinance ^TNX proxy
            // (cached 24h). Null degrades to "—" on the tile.
            pct={pulse.risk_free_change_pct ?? null}
            sparkline={macroSpark("INDIA10Y")}
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
          sparkline={macroSpark("GOLD")}
        />
        <Cell
          label="SILVER"
          value={
            pulse.silver_inr_per_10g != null
              ? `₹${Math.round(pulse.silver_inr_per_10g).toLocaleString("en-IN")}/10g`
              : "—"
          }
          pct={pulse.silver_usd_change_pct ?? null}
          sparkline={macroSpark("SILVER")}
        />
        <Cell
          label="CRUDE"
          value={
            pulse.crude_usd != null
              ? `$${pulse.crude_usd.toFixed(1)}/bbl`
              : "—"
          }
          pct={pulse.crude_usd_change_pct ?? null}
          sparkline={macroSpark("CRUDE")}
        />
        {showHubLink && (
          <Link
            href="/markets"
            className="flex items-center px-3 text-[11px] font-semibold text-brand hover:underline whitespace-nowrap"
          >
            Markets →
          </Link>
        )}
      </div>
    </div>
  )
}
