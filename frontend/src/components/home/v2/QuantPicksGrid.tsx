"use client"
// Quant Picks grid — 4 tiles backed by existing screener presets +
// custom screener queries. Each tile fetches independently.
// Presets supported by /api/v1/screener/preset/{name}:
//   - buffett        (score >= 60, mos >= 0, wide moat)  → Wide-Moat at Discount
//   - deep_value     (mos >= 30)                          → Deep Value
//   - growth_quality (revenue growth + margins)           → High-Margin Growers
// 4th tile: custom screener via /api/v1/screener/run?min_mos=15&min_score=50
//           framed as "Quality at a discount".

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { runPreset, runScreener } from "@/lib/api"
import type { ScreenerResponse } from "@/types/api"
import { Shield, TrendingDown, Rocket, Coins } from "lucide-react"

type TileConfig = {
  key: string
  title: string
  blurb: string
  icon: React.ComponentType<{ className?: string }>
  fetcher: () => Promise<ScreenerResponse>
  href: string
}

const TILES: TileConfig[] = [
  {
    key: "buffett",
    title: "Wide-Moat at Discount",
    blurb: "Score ≥ 60 · Wide moat · MoS ≥ 0",
    icon: Shield,
    fetcher: () => runPreset("buffett"),
    href: "/screener?preset=buffett",
  },
  {
    key: "deep_value",
    title: "Deep Value",
    blurb: "MoS ≥ 30%",
    icon: TrendingDown,
    fetcher: () => runPreset("deep-value"),
    href: "/screener?preset=deep-value",
  },
  {
    key: "growth_quality",
    title: "High-Margin Growers",
    blurb: "Revenue + margin filters",
    icon: Rocket,
    fetcher: () => runPreset("growth-quality"),
    href: "/screener?preset=growth-quality",
  },
  {
    key: "quality_discount",
    title: "Quality at a Discount",
    blurb: "Score ≥ 50 · MoS ≥ 15%",
    icon: Coins,
    fetcher: () => runScreener({ min_score: 50, min_mos: 15, page_size: 25 }),
    href: "/screener?min_score=50&min_mos=15",
  },
]

function Tile({ cfg }: { cfg: TileConfig }) {
  const { data, isLoading } = useQuery({
    queryKey: ["quant-tile", cfg.key],
    queryFn: cfg.fetcher,
    staleTime: 10 * 60 * 1000,
    retry: 1,
  })
  const Icon = cfg.icon
  const results = data?.results ?? []
  const total = data?.total ?? 0
  const top = results.slice(0, 3)

  return (
    <div className="bg-surface border border-border rounded-2xl p-4 flex flex-col">
      <div className="flex items-start justify-between mb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <Icon className="w-4 h-4 text-brand flex-shrink-0" />
            <h3 className="text-sm font-semibold text-ink truncate">{cfg.title}</h3>
          </div>
          <p className="text-[10px] text-caption">{cfg.blurb}</p>
        </div>
        <span className="text-base font-bold font-mono text-ink tabular-nums">
          {isLoading ? "…" : total}
        </span>
      </div>

      <div className="flex-1 mt-2 space-y-1">
        {isLoading ? (
          <>
            <div className="h-4 bg-border/60 rounded animate-pulse" />
            <div className="h-4 bg-border/60 rounded animate-pulse" />
            <div className="h-4 bg-border/60 rounded animate-pulse" />
          </>
        ) : top.length === 0 ? (
          <p className="text-[11px] text-caption">No matches today.</p>
        ) : (
          top.map(s => {
            const display = s.ticker.replace(/\.(NS|BO)$/, "")
            // Suppress MoS for tickers without a published fair value.
            // Showing "+49% MoS" on a stock whose analysis page admits
            // "no FV available — under review" is the kind of internal
            // contradiction the audit flagged. Badge instead.
            const v = (s.verdict || "").toLowerCase()
            const underReview =
              v === "data_limited" || v === "under_review" || v === "unavailable"
            return (
              <Link
                key={s.ticker}
                href={`/analysis/${display}`}
                className="flex items-center justify-between text-[11px] font-mono py-0.5 hover:text-brand"
              >
                <span className="font-semibold text-ink truncate">{display}</span>
                {underReview ? (
                  <span className="text-caption italic">Under Review</span>
                ) : (
                  <span className="text-green-600 dark:text-green-400">
                    {s.margin_of_safety >= 0 ? "+" : ""}
                    {s.margin_of_safety.toFixed(0)}%
                  </span>
                )}
              </Link>
            )
          })
        )}
      </div>

      <Link
        href={cfg.href}
        className="mt-3 text-[11px] font-semibold text-brand hover:underline"
      >
        See all →
      </Link>
    </div>
  )
}

export default function QuantPicksGrid() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {TILES.map(t => <Tile key={t.key} cfg={t} />)}
    </div>
  )
}
