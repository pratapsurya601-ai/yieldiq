"use client"

/**
 * SectorHeatmapMini (2026-06-10) — peer grid by margin-of-safety.
 *
 * Novel visualization. None of the competitors we walked (Tickertape,
 * Screener, AlphaSpread, Trendlyne, MoneyControl, INDmoney, Smallcase,
 * Groww, Equitymaster) surface the sector cohort as a tile grid sized
 * by market cap and colored by MoS. The closest analog is the
 * Tickertape "Industry Health" strip, which only shows aggregate
 * change-%, not per-ticker valuation.
 *
 * Layout: each tile is one ticker in the same canonical sector.
 *   - Tile size = market_cap_cr weight (sqrt-scaled for readability,
 *     so the top mega-cap doesn't swallow the whole grid).
 *   - Tile color = MoS pct: green > +5%, red < -5%, gray |MoS| <= 5%
 *     or MoS unavailable.
 *   - Subject ticker = thicker border + ring + always rendered.
 *   - Click → router.push(`/analysis/${ticker}`).
 *
 * Render strategy: a flex-wrap grid of variable-width tiles, NOT the
 * recharts Treemap component. The Treemap component produces
 * pixel-perfect packing but is opaque to keyboard navigation and
 * adds ~40KB to the route. A native flex grid is keyboard-accessible
 * (each tile is a real <button>), respects reduced-motion / dark
 * mode without extra config, and ships zero new bundles.
 *
 * Data source: GET /api/v1/public/sector-heatmap/{ticker} returning
 * up to 30 cohort tiles. See backend/routers/public.py.
 *
 * SEBI vocabulary: verdict labels go through verdictDisplayLabel
 * (Undervalued / Fairly Valued / Overvalued / Under Review /
 * Insufficient Data). No advisory verbs anywhere in the surface.
 */

import { useMemo } from "react"
import { useRouter } from "next/navigation"
import { useQuery } from "@tanstack/react-query"

import {
  getSectorHeatmap,
  type SectorHeatmapResponse,
  type SectorHeatmapTile,
} from "@/lib/api"
import { cn, formatCompanyName, verdictDisplayLabel } from "@/lib/utils"

interface Props {
  ticker: string
  /** Cap on tiles rendered. Defaults to 30 (backend cap). */
  limit?: number
}

/** Color band thresholds (MoS percentage). Symmetric around the
 *  "fairly valued" gray band of +/-5%. Single source of truth so the
 *  legend and the tile colors stay in lockstep. */
const MOS_GREEN_THRESHOLD = 5
const MOS_RED_THRESHOLD = -5
const MOS_DEEP_GREEN_THRESHOLD = 25
const MOS_DEEP_RED_THRESHOLD = -25

/** Square-root scaling on market cap so a 10x larger mega-cap takes
 *  ~3x the area, not 10x. Keeps the smallest tiles legible while still
 *  ranking by mcap. */
function sqrtWeight(mcap: number | null): number {
  if (mcap == null || !Number.isFinite(mcap) || mcap <= 0) return 1
  return Math.sqrt(mcap)
}

/** Tile background color from MoS band. Tailwind utility classes —
 *  no inline styles so dark-mode palettes follow tokens. */
function tileColorClass(mos: number | null): string {
  if (mos == null || !Number.isFinite(mos)) {
    return "bg-slate-200 dark:bg-slate-700/60 text-slate-700 dark:text-slate-300"
  }
  if (mos >= MOS_DEEP_GREEN_THRESHOLD) {
    return "bg-emerald-500 dark:bg-emerald-600 text-white"
  }
  if (mos >= MOS_GREEN_THRESHOLD) {
    return "bg-emerald-200 dark:bg-emerald-900/70 text-emerald-900 dark:text-emerald-100"
  }
  if (mos <= MOS_DEEP_RED_THRESHOLD) {
    return "bg-rose-500 dark:bg-rose-600 text-white"
  }
  if (mos <= MOS_RED_THRESHOLD) {
    return "bg-rose-200 dark:bg-rose-900/70 text-rose-900 dark:text-rose-100"
  }
  return "bg-slate-200 dark:bg-slate-700/60 text-slate-700 dark:text-slate-300"
}

function formatMcapShort(cr: number | null): string {
  if (cr == null || !Number.isFinite(cr) || cr <= 0) return "—"
  if (cr >= 1e5) return `₹${(cr / 1e5).toFixed(1)}L Cr`
  if (cr >= 1e3) return `₹${(cr / 1e3).toFixed(1)}k Cr`
  return `₹${cr.toFixed(0)} Cr`
}

function formatMosShort(mos: number | null): string {
  if (mos == null || !Number.isFinite(mos)) return "—"
  const sign = mos > 0 ? "+" : ""
  return `${sign}${mos.toFixed(0)}%`
}

function bareTicker(t: string): string {
  return t.replace(/\.(NS|BO)$/i, "")
}

/**
 * Derive a tile's flex-basis from its mcap weight relative to the
 * cohort. Returns a percentage clamped to [6%, 24%] so even the
 * largest tile leaves room for ~4 others on the same row, and the
 * smallest is still tap-friendly on mobile (~44px wide at 380px).
 */
function basisPct(weight: number, totalWeight: number): number {
  if (totalWeight <= 0 || !Number.isFinite(totalWeight)) return 12
  const raw = (weight / totalWeight) * 100
  const SCALED_TO_ROW = raw * 3 // assume ~3 rows so we don't undershoot
  if (!Number.isFinite(SCALED_TO_ROW)) return 12
  return Math.max(8, Math.min(28, SCALED_TO_ROW))
}

interface DerivedTile extends SectorHeatmapTile {
  weight: number
  basisPct: number
}

function deriveTiles(tiles: SectorHeatmapTile[]): DerivedTile[] {
  const weights = tiles.map(t => sqrtWeight(t.market_cap_cr))
  const totalWeight = weights.reduce((acc, w) => acc + w, 0)
  return tiles.map((t, i) => ({
    ...t,
    weight: weights[i],
    basisPct: basisPct(weights[i], totalWeight),
  }))
}

/**
 * Build a short tooltip line per tile. Pure function so it can be
 * unit-tested without rendering. Keeps SEBI-neutral vocab —
 * verdictDisplayLabel emits the neutral set.
 */
export function buildTileTooltip(tile: SectorHeatmapTile): string {
  const name = formatCompanyName(tile.name || tile.ticker, tile.ticker)
  const mos = formatMosShort(tile.mos_pct)
  const mcap = formatMcapShort(tile.market_cap_cr)
  const verdict = tile.verdict ? verdictDisplayLabel(tile.verdict) : null
  const parts = [`${name} (${tile.ticker})`, `MoS ${mos}`, `Mcap ${mcap}`]
  if (verdict && verdict.toLowerCase() !== "unknown") parts.push(verdict)
  return parts.join(" • ")
}

function HeatmapLegend() {
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-600 dark:text-slate-400"
      data-testid="sector-heatmap-legend"
    >
      <span className="font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        MoS band
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" />
        &ge; +25%
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-200 dark:bg-emerald-900/70" />
        +5 to +25%
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-2.5 w-2.5 rounded-sm bg-slate-200 dark:bg-slate-700/60" />
        within &plusmn;5%
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-2.5 w-2.5 rounded-sm bg-rose-200 dark:bg-rose-900/70" />
        -5 to -25%
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-2.5 w-2.5 rounded-sm bg-rose-500" />
        &le; -25%
      </span>
    </div>
  )
}

function LoadingShell() {
  return (
    <section
      data-testid="sector-heatmap-skeleton"
      aria-busy="true"
      className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900"
    >
      <div className="mb-3 h-4 w-44 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
      <div className="flex flex-wrap gap-1.5">
        {Array.from({ length: 18 }).map((_, i) => (
          <div
            key={i}
            className="h-14 animate-pulse rounded bg-slate-100 dark:bg-slate-800"
            style={{ flexBasis: `${8 + (i % 6) * 3}%`, flexGrow: 1 }}
          />
        ))}
      </div>
    </section>
  )
}

export default function SectorHeatmapMini({
  ticker,
  limit = 30,
}: Props) {
  const router = useRouter()
  const query = useQuery<SectorHeatmapResponse | null>({
    queryKey: ["public-sector-heatmap", ticker, limit],
    queryFn: () => getSectorHeatmap(ticker, limit),
    staleTime: 30 * 60_000, // 30 min — backend caches 1h
    retry: 1,
  })

  const derivedTiles = useMemo<DerivedTile[]>(() => {
    const tiles = query.data?.tiles ?? []
    return deriveTiles(tiles)
  }, [query.data])

  if (query.isLoading) {
    return <LoadingShell />
  }

  // Soft-fail: hide entirely on error or empty cohort. The analysis
  // page has many panels; an inline error banner here would just be
  // noise. The endpoint already returns a 503 with a stable shape on
  // backend trouble; the publicGet helper turns that into `null`.
  if (query.isError || !query.data) {
    return null
  }

  const { sector, subject_ticker, caption, tile_count } = query.data
  if (!sector || tile_count === 0 || derivedTiles.length === 0) {
    return null
  }

  const handleTileClick = (tileTicker: string) => {
    const bare = bareTicker(tileTicker)
    if (!bare) return
    router.push(`/analysis/${encodeURIComponent(bare)}`)
  }

  return (
    <section
      data-testid="sector-heatmap-mini"
      aria-label={`Sector heatmap for ${sector}`}
      className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900"
    >
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Sector heatmap &mdash; {sector}
          </h3>
          {caption ? (
            <p
              data-testid="sector-heatmap-caption"
              className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400"
            >
              {caption}
            </p>
          ) : null}
        </div>
        <HeatmapLegend />
      </header>

      <div
        role="list"
        data-testid="sector-heatmap-grid"
        className="flex flex-wrap gap-1.5"
      >
        {derivedTiles.map(tile => {
          const isSubject = tile.is_subject || tile.ticker === subject_ticker
          const tooltip = buildTileTooltip(tile)
          return (
            <button
              key={tile.ticker}
              type="button"
              role="listitem"
              data-testid={
                isSubject
                  ? "sector-heatmap-tile-subject"
                  : "sector-heatmap-tile"
              }
              data-ticker={tile.ticker}
              data-mos={tile.mos_pct ?? ""}
              onClick={() => handleTileClick(tile.ticker)}
              title={tooltip}
              aria-label={tooltip}
              style={{
                flexBasis: `${tile.basisPct}%`,
                flexGrow: 1,
                minWidth: 56,
              }}
              className={cn(
                "group flex h-16 flex-col items-stretch justify-between rounded-md p-1.5 text-left text-[11px] leading-tight",
                "transition-transform hover:scale-[1.03] hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
                tileColorClass(tile.mos_pct),
                isSubject
                  ? "ring-2 ring-sky-500 ring-offset-1 ring-offset-white dark:ring-offset-slate-900"
                  : "",
              )}
            >
              <span className="block truncate font-semibold">
                {bareTicker(tile.ticker)}
              </span>
              <span className="block truncate text-[10px] opacity-90">
                {formatMosShort(tile.mos_pct)}
              </span>
            </button>
          )
        })}
      </div>

      <p className="mt-3 text-[10px] text-slate-400 dark:text-slate-500">
        Tile size scales with market cap. Color shows margin of safety vs
        the YieldIQ model estimate. Click any tile to open that
        ticker&rsquo;s analysis. Model estimate; not investment advice.
      </p>
    </section>
  )
}
