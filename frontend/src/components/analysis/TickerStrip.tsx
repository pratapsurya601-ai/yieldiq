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
import { getMarketPulse, getPublicIndices, getWatchlist } from "@/lib/api"
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
    // Auth-gated — only fetch when we have a token, otherwise the
    // request 401s and the strip fell back to em-dashes (the bug
    // this fix addresses). Logged-out users get /api/v1/public/indices
    // via the fallback query below.
    enabled: !!token,
    // /market/pulse is currently 10s+ cold on Railway. Keep the result
    // stable for 5 min so sibling pages don't re-trigger compute. The
    // strip renders em-dashes while the fetch is in flight — cosmetic,
    // not blocking.
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    retry: 0,
  })

  // Logged-out fallback: hit the public indices endpoint so the strip
  // shows real last-close numbers instead of em-dashes.
  const { data: publicIndices } = useQuery({
    queryKey: ["public-indices"],
    queryFn: getPublicIndices,
    enabled: !token,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 0,
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
  // Combine logged-in pulse (authoritative when present) and the
  // logged-out public endpoint. Either source produces rows shaped
  // {name, price, change_pct} which is the MarketIndex contract.
  const sources: Array<{ name: string; price: number; change_pct: number | null }> = []
  for (const i of pulse?.indices ?? []) sources.push(i)
  for (const i of publicIndices?.indices ?? []) sources.push(i)
  for (const i of sources) {
    if (i.price == null) continue
    const row: MarketIndex = {
      name: i.name,
      price: i.price,
      change_pct: i.change_pct ?? 0,
    }
    byName.set(i.name.toUpperCase(), row)
    // Also index by short variants commonly returned by backend.
    // Use exact-name matches only — substring matches like
    // .includes("nifty") falsely match "Nifty Auto", "Nifty Consumer
    // Durables", etc., causing the last sector index in the list to
    // overwrite the real NIFTY 50 row (P0 bug fix 2026-04-30).
    const lname = i.name.toLowerCase().trim()
    if (lname === "nifty 50" || lname === "^nsei") byName.set("NIFTY 50", row)
    if (lname === "nifty bank" || lname === "bank nifty" || lname === "^nsebank")
      byName.set("BANK NIFTY", row)
    if (lname === "sensex" || lname === "^bsesn") byName.set("SENSEX", row)
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
