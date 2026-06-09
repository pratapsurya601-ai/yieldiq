"use client"
// IndexDashboardsRow — /markets hub (2026-06-09).
//
// Enriches the static "Index dashboards" cards (NIFTY 50 / NIFTY BANK /
// NIFTY IT) with the index's current LEVEL + 1d change % from the same
// /api/v1/market/pulse call MarketsStrip uses. Card reads:
//
//   NIFTY 50              23,242  +0.6%
//   The 50 largest...
//
// Re-uses the same React-Query key as MarketsStrip so the page only
// pays for one /pulse round-trip and both surfaces stay in lockstep.
// Falls back to the descriptive blurb when pulse data isn't loaded yet
// (no flash of incorrect numbers, no skeleton flicker on each tile).

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { getMarketPulse } from "@/lib/api"
import { formatPct } from "@/lib/utils"

interface IndexEntry {
  href: string
  /** Index label from /pulse — used to look up the live tile. */
  pulseName: string
  /** Display name shown on the card heading. */
  name: string
  description: string
}

// Mirrors the entries from the static page header. Pulse `name` may
// arrive with or without "NSE" prefix, so we use includes() lookups.
const INDEX_DASHBOARDS: IndexEntry[] = [
  {
    href: "/nifty50",
    pulseName: "NIFTY 50",
    name: "NIFTY 50",
    description:
      "The 50 largest NSE-listed companies by free-float market cap. Sector breakdown, constituent table, and cohort median valuation lens.",
  },
  {
    href: "/nifty-bank",
    pulseName: "NIFTY BANK",
    name: "NIFTY BANK",
    description:
      "The 12-stock NIFTY Bank index — public-sector and private-sector banks side by side. P/B and residual-income lens (banks don't use DCF).",
  },
  {
    href: "/nifty-it",
    pulseName: "NIFTY IT",
    name: "NIFTY IT",
    description:
      "The Indian IT services cohort — TCS, Infosys, Wipro, HCLTech, and second-tier exporters. Tier-1 vs Tier-2 segmentation built in.",
  },
]

function formatLevel(price: number | undefined | null): string {
  if (price === null || price === undefined || !Number.isFinite(price)) return "—"
  return price.toLocaleString("en-IN", { maximumFractionDigits: 2 })
}

function changeClass(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "text-caption"
  return pct >= 0
    ? "text-green-700 dark:text-green-400"
    : "text-rose-700 dark:text-rose-400"
}

export default function IndexDashboardsRow() {
  // Same queryKey as MarketsStrip — re-uses the in-flight cache.
  // No re-fetch needed on this page; MarketsStrip already manages
  // the 60s polling cadence.
  const { data: pulse } = useQuery({
    queryKey: ["markets-strip"],
    queryFn: () => getMarketPulse(true),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  // Build a quick lookup from pulse.indices by upper-cased name. Two
  // matchers ("contains" / "equals") because the pulse feed isn't 100%
  // consistent on the "NSE NIFTY 50" vs "NIFTY 50" prefix.
  const indexByName = new Map<string, { price: number; change_pct: number }>()
  for (const idx of pulse?.indices ?? []) {
    indexByName.set(idx.name.toUpperCase(), {
      price: idx.price,
      change_pct: idx.change_pct,
    })
  }

  function lookup(pulseName: string): { price: number; change_pct: number } | null {
    const target = pulseName.toUpperCase()
    // Exact first, then substring match.
    const exact = indexByName.get(target)
    if (exact) return exact
    for (const [key, val] of indexByName.entries()) {
      if (key.includes(target)) return val
    }
    return null
  }

  return (
    <div className="grid sm:grid-cols-3 gap-3">
      {INDEX_DASHBOARDS.map(idx => {
        const live = lookup(idx.pulseName)
        return (
          <Link
            key={idx.href}
            href={idx.href}
            className="block bg-bg dark:bg-surface border border-border rounded-xl p-5 hover:border-brand hover:shadow-sm transition"
            data-testid="index-dashboard-card"
          >
            <div className="flex items-baseline justify-between gap-2 mb-2">
              <p className="text-base font-bold text-ink truncate">{idx.name}</p>
              {live && (
                <div className="flex items-baseline gap-2 flex-shrink-0">
                  <span
                    className="text-sm font-mono font-semibold text-ink tabular-nums"
                    data-testid="index-dashboard-level"
                  >
                    {formatLevel(live.price)}
                  </span>
                  <span
                    className={`text-xs font-mono tabular-nums ${changeClass(live.change_pct)}`}
                    data-testid="index-dashboard-change"
                  >
                    {Number.isFinite(live.change_pct) ? formatPct(live.change_pct) : "—"}
                  </span>
                </div>
              )}
            </div>
            <p className="text-xs text-caption leading-relaxed">
              {idx.description}
            </p>
          </Link>
        )
      })}
    </div>
  )
}
