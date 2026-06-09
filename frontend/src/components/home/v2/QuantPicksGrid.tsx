"use client"
// Quant Picks grid — 4 tiles backed by existing screener presets +
// custom screener queries. Each tile fetches independently.
// Presets supported by /api/v1/screener/preset/{name}:
//   - buffett        (score >= 60, mos >= 0, wide moat)  → Wide-Moat at Discount
//   - deep_value     (mos >= 30)                          → Deep Value
//   - growth_quality (revenue growth + margins)           → High-Margin Growers
// 4th tile: custom screener via /api/v1/screener/run?min_mos=20&min_score=65
//           framed as "Quality at a discount".
//
// 2026-05-21 (Day-70): tightened from min_score=50/min_mos=15 (which
// returned 702 stocks — the 2026-05-20 audit flagged this as "filter
// too loose, not a quality-at-a-discount list at all") to
// min_score=65/min_mos=20. Goal: 30-80 names so the tile actually
// surfaces opinionated picks, not the entire mid-cap universe.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import TickerAvatar from "@/components/common/TickerAvatar"
import {
  QUANT_PRESETS,
  quantPresetQueryKey,
  type QuantPresetConfig,
} from "./quantPicksPresets"
import { Shield, TrendingDown, Rocket, Coins } from "lucide-react"

type TileConfig = QuantPresetConfig & {
  icon: React.ComponentType<{ className?: string }>
}

// Icon assignment is owned here (the shared registry is icon-free so
// the TodaysMovers fallback doesn't drag lucide-react into its bundle
// for no reason).
const ICONS: Record<QuantPresetConfig["key"], React.ComponentType<{ className?: string }>> = {
  buffett: Shield,
  deep_value: TrendingDown,
  growth_quality: Rocket,
  quality_discount: Coins,
}

const TILES: TileConfig[] = QUANT_PRESETS.map(p => ({ ...p, icon: ICONS[p.key] }))

function Tile({ cfg }: { cfg: TileConfig }) {
  const { data, isLoading } = useQuery({
    queryKey: quantPresetQueryKey(cfg.key),
    queryFn: cfg.fetcher,
    staleTime: 10 * 60 * 1000,
    retry: 1,
  })
  const Icon = cfg.icon
  const results = data?.results ?? []
  const total = data?.total ?? 0
  const top = results.slice(0, 3)
  // The backend already sorts each named preset's leaderboard by its
  // primary signal (MoS desc for buffett/deep_value, revenue-CAGR desc
  // for growth_quality — see `_PRESET_SORT_KEYS` in
  // backend/routers/screener.py). The custom "quality_discount" tile
  // runs through `runScreener({...})` which also orders by PE asc /
  // MoS proxy, so `results.slice(0, 3)` is already "best 3 first" for
  // every tile. No client-side re-sort needed.
  const remaining = Math.max(0, total - top.length)

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
        <span
          className="text-base font-bold font-mono text-ink tabular-nums"
          data-testid={`quant-tile-count-${cfg.key}`}
        >
          {isLoading ? "…" : total}
        </span>
      </div>

      <div className="flex-1 mt-2 space-y-1" data-testid={`quant-tile-rows-${cfg.key}`}>
        {isLoading ? (
          <>
            <div className="h-5 bg-border/60 rounded animate-pulse" />
            <div className="h-5 bg-border/60 rounded animate-pulse" />
            <div className="h-5 bg-border/60 rounded animate-pulse" />
          </>
        ) : top.length === 0 ? (
          // No matches at all — keep the existing "No matches today"
          // copy because the user has nothing to refine FROM. The
          // sparse-but-non-empty case (1-2 matches) gets the
          // refine-filters prompt below instead.
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
                className="flex items-center gap-2 text-[11px] font-mono py-0.5 hover:bg-bg/40 rounded transition group"
                data-testid="quant-tile-row"
              >
                <TickerAvatar ticker={s.ticker} size="sm" />
                <span className="font-semibold text-ink truncate group-hover:text-brand min-w-0 flex-1">
                  {display}
                </span>
                {underReview ? (
                  <span className="text-caption italic flex-shrink-0">Under Review</span>
                ) : (
                  <span className="text-green-600 dark:text-green-400 flex-shrink-0 tabular-nums">
                    MoS {s.margin_of_safety >= 0 ? "+" : ""}
                    {s.margin_of_safety.toFixed(0)}%
                  </span>
                )}
              </Link>
            )
          })
        )}
      </div>

      {/*
        Footer behaviour:
          - 0 matches  → "Browse all screens →" (kept generic; the user
                         has nothing to refine FROM on this tile so we
                         send them to the full screener landing).
          - 1-2 matches → "Tap to refine filters →" — the preset is
                         capable of returning more but the live universe
                         is sparse today; the screener page is where they
                         loosen the gates.
          - 3+ matches → "See N more →" linking to the preset page.
      */}
      {!isLoading && top.length > 0 && top.length < 3 && (
        <Link
          href={cfg.href}
          className="mt-3 text-[11px] font-semibold text-brand hover:underline"
          data-testid={`quant-tile-refine-${cfg.key}`}
        >
          Tap to refine filters →
        </Link>
      )}
      {!isLoading && top.length >= 3 && (
        <Link
          href={cfg.href}
          className="mt-3 text-[11px] font-semibold text-brand hover:underline"
          data-testid={`quant-tile-more-${cfg.key}`}
        >
          {remaining > 0 ? `See ${remaining} more →` : "View all →"}
        </Link>
      )}
      {!isLoading && top.length === 0 && (
        <Link
          href={cfg.href}
          className="mt-3 text-[11px] font-semibold text-brand hover:underline"
        >
          Browse all screens →
        </Link>
      )}
      {isLoading && (
        <span className="mt-3 text-[11px] font-semibold text-brand/60">
          See all →
        </span>
      )}
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
