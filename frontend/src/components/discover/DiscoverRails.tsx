"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import type { ScreenerStock } from "@/types/api"
import UnlockBadge from "@/components/payg/UnlockBadge"

// The three rails on /discover. SectorLeaders composes existing YieldIQ 50
// data (no backend work). NearLowsRail + LowestPERail fetch from new public
// endpoints that pull from live_quotes + market_metrics + analysis_cache.

const TRACKED_SECTORS = ["Banking", "IT", "Pharma", "FMCG", "Auto", "Energy"] as const
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function classifySector(raw: string | undefined | null): string | null {
  if (!raw) return null
  const s = raw.toLowerCase()
  if (s.includes("bank") || s.includes("financial")) return "Banking"
  if (s.includes("tech") || s.includes("software") || s.includes("it ") || s === "it") return "IT"
  if (s.includes("pharma") || s.includes("health") || s.includes("drug")) return "Pharma"
  if (s.includes("fmcg") || s.includes("consumer defensive") || s.includes("staple")) return "FMCG"
  if (s.includes("auto")) return "Auto"
  if (s.includes("energy") || s.includes("oil") || s.includes("gas") || s.includes("power") || s.includes("utilit")) return "Energy"
  return null
}

interface SectorLeadersProps {
  stocks: ScreenerStock[]
}

export function SectorLeaders({ stocks }: SectorLeadersProps) {
  const leaders = new Map<string, ScreenerStock>()
  for (const stock of stocks) {
    const bucket = classifySector(stock.sector)
    if (!bucket) continue
    if (!TRACKED_SECTORS.includes(bucket as typeof TRACKED_SECTORS[number])) continue
    if (!leaders.has(bucket)) leaders.set(bucket, stock)
  }
  type SectorName = typeof TRACKED_SECTORS[number]
  const items = TRACKED_SECTORS
    .map((sector) => ({ sector, stock: leaders.get(sector) }))
    .filter((x): x is { sector: SectorName; stock: ScreenerStock } => !!x.stock)

  if (items.length === 0) return null

  return (
    <section>
      <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-2">Sector leaders</p>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {items.map(({ sector, stock }) => (
          <Link
            key={sector}
            href={`/analysis/${stock.ticker}`}
            className="bg-surface rounded-xl border border-border p-3 hover:border-brand hover:shadow-sm active:scale-[0.98] transition"
          >
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5 min-w-0">
                <p className="text-sm font-bold text-ink truncate">{stock.ticker.replace(".NS", "")}</p>
                <UnlockBadge ticker={stock.ticker} size="sm" />
              </div>
              <span className="text-[9px] font-semibold text-caption bg-bg rounded px-1.5 py-0.5 uppercase tracking-wider">{sector}</span>
            </div>
            <p className="text-base font-bold text-brand font-mono">
              {stock.margin_of_safety != null
                ? `${stock.margin_of_safety > 0 ? "+" : ""}${stock.margin_of_safety.toFixed(0)}%`
                : "\u2014"}
            </p>
            <p className="text-[10px] text-caption">MoS &middot; Model estimate</p>
          </Link>
        ))}
      </div>
      <p className="text-[10px] text-caption mt-1">Highest-scoring stock in each sector from YieldIQ 50. Not investment advice.</p>
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────────
// 52-week lows with durable fundamentals
// ─────────────────────────────────────────────────────────────────────

interface NearLowStock {
  ticker: string
  company_name: string
  price: number
  w52_low: number
  w52_high: number | null
  distance_pct: number
  yieldiq_score: number
}

export function NearLowsRail() {
  const [stocks, setStocks] = useState<NearLowStock[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/api/v1/public/near-52w-lows?limit=6&max_distance_pct=25&min_score=35`)
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((d) => { if (!cancelled) setStocks(d.stocks || []) })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [])

  return (
    <section>
      <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-2">52-week lows with durable fundamentals</p>
      {stocks === null && !error && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="bg-surface rounded-xl border border-border p-4 min-h-[96px]">
              <div className="skeleton h-3 w-16 rounded mb-2" />
              <div className="skeleton h-4 w-12 rounded mb-2" />
              <div className="skeleton h-3 w-20 rounded" />
            </div>
          ))}
        </div>
      )}
      {error && (
        <div className="bg-surface rounded-xl border border-border p-4 text-center">
          <p className="text-xs text-caption">Couldn&rsquo;t load right now. Try again shortly.</p>
        </div>
      )}
      {stocks !== null && stocks.length === 0 && !error && (
        <div className="bg-surface rounded-xl border border-border p-4 text-center">
          <p className="text-xs text-caption">No stocks currently within 25% of their 52-week low with a quality score &ge; 35. Markets rallied or our cache is warming.</p>
        </div>
      )}
      {stocks !== null && stocks.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {stocks.map((s) => (
            <Link
              key={s.ticker}
              href={`/analysis/${s.ticker}`}
              className="bg-surface rounded-xl border border-border p-3 hover:border-brand hover:shadow-sm active:scale-[0.98] transition"
            >
              <div className="flex items-center justify-between mb-1">
                <p className="text-sm font-bold text-ink truncate">{s.ticker.replace(".NS", "")}</p>
                <span className="text-[9px] font-semibold text-success bg-bg rounded px-1.5 py-0.5 uppercase tracking-wider">Score {s.yieldiq_score}</span>
              </div>
              <p className="text-base font-bold text-ink font-mono tabular-nums">
                {s.price != null ? `\u20b9${s.price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "\u2014"}
              </p>
              <p className="text-[10px] text-caption">
                {s.distance_pct == null
                  ? "\u2014"
                  : s.distance_pct <= 1
                    ? "At 52w low"
                    : `+${s.distance_pct.toFixed(1)}% above 52w low`}
              </p>
            </Link>
          ))}
        </div>
      )}
      <p className="text-[10px] text-caption mt-1">Top-400 by market cap, within 25% of 52w low, YieldIQ score &ge; 35. Model estimate.</p>
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Lowest P/E in YieldIQ universe
// ─────────────────────────────────────────────────────────────────────

interface LowPEStock {
  ticker: string
  company_name: string
  pe_ratio: number
  yieldiq_score: number
}

interface LowestPERailProps {
  stocks: ScreenerStock[]
}

export function LowestPERail({ stocks: _unused }: LowestPERailProps) {
  void _unused
  const [items, setItems] = useState<LowPEStock[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/api/v1/public/lowest-pe?limit=6&min_score=35&max_pe=60`)
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((d) => { if (!cancelled) setItems(d.stocks || []) })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [])

  return (
    <section>
      <p className="text-[10px] font-bold text-caption uppercase tracking-widest mb-2">Lowest P/E with durable fundamentals</p>
      {items === null && !error && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="bg-surface rounded-xl border border-border p-4 min-h-[96px]">
              <div className="skeleton h-3 w-16 rounded mb-2" />
              <div className="skeleton h-4 w-12 rounded mb-2" />
              <div className="skeleton h-3 w-20 rounded" />
            </div>
          ))}
        </div>
      )}
      {error && (
        <div className="bg-surface rounded-xl border border-border p-4 text-center">
          <p className="text-xs text-caption">Couldn&rsquo;t load right now. Try again shortly.</p>
        </div>
      )}
      {items !== null && items.length === 0 && !error && (
        <div className="bg-surface rounded-xl border border-border p-4 text-center">
          <p className="text-xs text-caption">No stocks currently under P/E 60 with a quality score &ge; 35.</p>
        </div>
      )}
      {items !== null && items.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {items.map((s) => (
            <Link
              key={s.ticker}
              href={`/analysis/${s.ticker}`}
              className="bg-surface rounded-xl border border-border p-3 hover:border-brand hover:shadow-sm active:scale-[0.98] transition"
            >
              <div className="flex items-center justify-between mb-1">
                <p className="text-sm font-bold text-ink truncate">{s.ticker.replace(".NS", "")}</p>
                <span className="text-[9px] font-semibold text-success bg-bg rounded px-1.5 py-0.5 uppercase tracking-wider">Score {s.yieldiq_score}</span>
              </div>
              <p className="text-base font-bold text-ink font-mono tabular-nums">
                {s.pe_ratio != null ? `${s.pe_ratio.toFixed(1)}\u00d7` : "\u2014"}
              </p>
              <p className="text-[10px] text-caption">P/E ratio</p>
            </Link>
          ))}
        </div>
      )}
      <p className="text-[10px] text-caption mt-1">Lowest P/E stocks with YieldIQ score &ge; 35 and P/E &le; 60. Model estimate.</p>
    </section>
  )
}
