"use client"

/**
 * TickerStrip — the Bloomberg-style strip above the editorial hero.
 *
 *   INDICES · NIFTY 50 24,612.40 +0.32% · SENSEX 80,814.55 +0.41% · ...
 *   WATCHLIST · TCS -1.24% · INFY +0.87% · ...
 *
 * Dark bg, mono font, horizontal scroll on mobile. Real indices come
 * from /api/v1/market/pulse (same payload used on the home page).
 * Watchlist comes from /api/v1/watchlist — only fetched when authed.
 * If indices are missing we show em-dashes rather than inventing numbers.
 */

import { useQuery } from "@tanstack/react-query"
import { getMarketPulse, getWatchlist } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import type { MarketIndex, WatchlistItemResponse } from "@/types/api"

function fmtIndex(v: number): string {
  return v.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function signedPct(v: number): string {
  const sign = v >= 0 ? "+" : "\u2212" // proper minus sign
  return `${sign}${Math.abs(v).toFixed(2)}%`
}

function deltaClass(change: number): string {
  if (change > 0) return "text-success"
  if (change < 0) return "text-danger"
  return "text-body"
}

/** Single logical cell: label + value + optional % change. */
function Cell({
  label,
  value,
  change,
}: {
  label: string
  value?: string
  change?: number | null
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="font-semibold text-bg">{label}</span>
      {value && <span className="tabular-nums text-body">{value}</span>}
      {change !== null && change !== undefined && (
        <span className={`tabular-nums ${deltaClass(change)}`}>{signedPct(change)}</span>
      )}
    </span>
  )
}

function Dot() {
  return <span aria-hidden className="text-border mx-2">·</span>
}

export default function TickerStrip() {
  const token = useAuthStore((s) => s.token)

  const { data: pulse } = useQuery({
    queryKey: ["market-pulse"],
    // No macro — we only need indices here. Keep the payload small.
    queryFn: () => getMarketPulse(false),
    staleTime: 60 * 1000,
    // Avoid SSR — this is a client strip that hydrates after paint so the
    // hero LCP isn't blocked by market-pulse fetch.
    refetchOnWindowFocus: false,
    retry: 1,
  })

  const { data: watchlist } = useQuery<WatchlistItemResponse[]>({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  // Pick the three indices we care about, in order.
  const indexOrder = ["NIFTY 50", "SENSEX", "BANK NIFTY"]
  const byName = new Map<string, MarketIndex>()
  for (const i of pulse?.indices ?? []) {
    byName.set(i.name.toUpperCase(), i)
    // Also index by short variants commonly returned by backend.
    if (i.name.toLowerCase().includes("nifty bank")) byName.set("BANK NIFTY", i)
    if (i.name.toLowerCase().includes("nifty") && !i.name.toLowerCase().includes("bank"))
      byName.set("NIFTY 50", i)
    if (i.name.toLowerCase().includes("sensex")) byName.set("SENSEX", i)
  }

  return (
    <div
      className="w-full bg-ink text-body border-b border-border font-mono text-[11px] tracking-wide"
      role="region"
      aria-label="Market indices and watchlist"
    >
      <div className="max-w-screen-xl mx-auto overflow-x-auto whitespace-nowrap px-4 py-1.5 flex items-center">
        <span className="font-semibold text-caption mr-3 uppercase tracking-[0.15em]">Indices</span>
        {indexOrder.map((name, i) => {
          const hit = byName.get(name)
          return (
            <span key={name} className="inline-flex items-center">
              {i > 0 && <Dot />}
              {hit ? (
                <Cell label={name} value={fmtIndex(hit.price)} change={hit.change_pct} />
              ) : (
                // TODO wire to /api/v1/indices — for now we honestly render
                // em-dashes rather than inventing numbers when the backend
                // hasn't populated this index.
                <Cell label={name} value={"\u2014"} change={null} />
              )}
            </span>
          )
        })}

        {watchlist && watchlist.length > 0 && (
          <>
            <Dot />
            <span className="font-semibold text-caption mx-2 uppercase tracking-[0.15em]">
              Watchlist
            </span>
            {watchlist.slice(0, 5).map((w, i) => {
              const display = w.ticker.replace(".NS", "").replace(".BO", "")
              // We don't have live % on the watchlist payload — omit the
              // change cell rather than fake it. Users tapping through get
              // real numbers on the analysis page.
              return (
                <span key={w.ticker} className="inline-flex items-center">
                  {i > 0 && <Dot />}
                  <Cell label={display} />
                </span>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}
