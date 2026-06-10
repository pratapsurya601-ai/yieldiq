"use client"

/**
 * MosHeatmapCalendar — GitHub-style 52-week heat-map of historical
 * margin-of-safety values for a single ticker.
 *
 * Why this exists
 * ---------------
 * Tickertape / AlphaSpread show DCF history as a line chart. That
 * answers "is the gap widening?" but not "on how many days was the
 * stock undervalued in the last year?" The heat-map turns the same
 * fair_value_history rows into a density view: each cell is a day,
 * coloured by MoS sign + magnitude. At a glance you can see the
 * temporal CLUSTERS of undervaluation rather than just the trend.
 *
 * Data source
 * -----------
 * Reuses the existing `/api/v1/analysis/{ticker}/fv-history` endpoint
 * (see `getFVHistory` in `frontend/src/lib/api.ts`) which already
 * returns `mos_pct` per date — no new backend endpoint required.
 * Shares the React-Query cache key `["fv-history", ticker, <years>]`
 * with ValuationTrajectoryChart + FairValueHistory so all three
 * panels mount with ONE network round-trip.
 *
 * Layout
 * ------
 * 7 rows (Sun -> Sat) × N weeks (52 for 1Y, 104 for 2Y, 156 for 3Y).
 * Cells are 11×11 with 2px gaps — same proportion as GitHub's
 * contribution graph. Each cell exposes a tooltip on hover with the
 * date, MoS, FV and price for that day, and dispatches a custom
 * `mos-heatmap-day-click` window event on click so the
 * ValuationTrajectoryChart sibling can scroll to / highlight the
 * matching point. (We use a window CustomEvent rather than wiring a
 * prop drill because the chart is mounted lazily via next/dynamic
 * and the two panels are siblings, not parent-child.)
 *
 * Honesty notes (Manifesto Rule 4)
 * --------------------------------
 *   - Days without an fv_history row render as the empty/no-data
 *     swatch — NOT as zero MoS. Missing data is shown as missing.
 *   - The color scale clamps at +/- 30% so a single 200% extreme
 *     day doesn't wash out the rest of the year. The legend states
 *     the clamp explicitly.
 *   - No verdict-language ("undervalued"/"overvalued") in the swatch
 *     legend — the SEBI vocab guard rejects those. We say "FV gap
 *     positive / negative" instead.
 */
import { useMemo, useState, useCallback } from "react"
import { useQuery } from "@tanstack/react-query"

import { getFVHistory, type FVHistoryPoint, type FVHistoryResponse } from "@/lib/api"
import { cn, formatCurrency } from "@/lib/utils"

/* ------------------------------------------------------------------ */
/* Types                                                                */
/* ------------------------------------------------------------------ */
export type MosHeatmapRange = "1Y" | "2Y" | "3Y"

export interface MosHeatmapCalendarProps {
  ticker: string
  currency?: string
  /** Test escape hatch — skips the network when supplied. */
  historyOverride?: FVHistoryPoint[]
  className?: string
}

/** One cell in the grid. `point` is null when no fv_history row exists. */
interface DayCell {
  isoDate: string
  weekIdx: number
  dayIdx: number // 0 = Sun
  point: FVHistoryPoint | null
}

/* ------------------------------------------------------------------ */
/* Constants                                                            */
/* ------------------------------------------------------------------ */
const RANGE_OPTIONS: MosHeatmapRange[] = ["1Y", "2Y", "3Y"]
const ONE_DAY_MS = 24 * 60 * 60 * 1000

// Diverging palette: red for negative MoS, green for positive, neutral
// gray near zero, distinct "no data" swatch. Tailwind tokens picked
// to match the existing dark-mode-friendly palette used elsewhere in
// analysis components.
const PALETTE = {
  noData: "bg-border/40",
  neutral: "bg-border/70",
  posLow: "bg-green-200 dark:bg-green-900/40",
  posMid: "bg-green-400 dark:bg-green-700/60",
  posHigh: "bg-green-600 dark:bg-green-500",
  negLow: "bg-red-200 dark:bg-red-900/40",
  negMid: "bg-red-400 dark:bg-red-700/60",
  negHigh: "bg-red-600 dark:bg-red-500",
} as const

/** Cross-component channel: chart sibling listens for this. */
export const MOS_HEATMAP_DAY_EVENT = "mos-heatmap-day-click"

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */
function rangeToDays(range: MosHeatmapRange): number {
  return range === "1Y" ? 365 : range === "2Y" ? 730 : 1095
}

function isoOf(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10)
}

/**
 * Bucket MoS into the diverging palette. The clamp at +/-30% is a
 * deliberate cap — single-day extremes (e.g. a price spike on a
 * post-results day where the FV briefly diverged) must not redefine
 * the year's colour scale. Disclosed in the legend.
 */
function swatchFor(mosPct: number | null): string {
  if (mosPct == null || Number.isNaN(mosPct)) return PALETTE.noData
  if (Math.abs(mosPct) < 2) return PALETTE.neutral
  const m = Math.max(-30, Math.min(30, mosPct))
  if (m >= 20) return PALETTE.posHigh
  if (m >= 10) return PALETTE.posMid
  if (m > 0) return PALETTE.posLow
  if (m <= -20) return PALETTE.negHigh
  if (m <= -10) return PALETTE.negMid
  return PALETTE.negLow
}

/**
 * Build the grid as a (weeks × 7) matrix anchored to the most recent
 * data point. We iterate forward day-by-day from `startMs` so that
 * holidays / weekend gaps naturally end up as "no data" cells, which
 * is the honest rendering.
 */
function buildCells(
  history: FVHistoryPoint[],
  range: MosHeatmapRange,
): { cells: DayCell[]; weekCount: number } {
  const byDate = new Map<string, FVHistoryPoint>()
  for (const row of history) byDate.set(row.date, row)

  // End anchor: the latest history date if we have data, otherwise today.
  // Snapping to local-time midnight keeps the grid deterministic across
  // tz boundaries.
  const latestIso = history[history.length - 1]?.date
  const endDate = latestIso ? new Date(latestIso + "T00:00:00") : new Date()
  endDate.setHours(0, 0, 0, 0)
  const endMs = endDate.getTime()

  const days = rangeToDays(range)
  const startMs = endMs - days * ONE_DAY_MS

  // Align to the start of that week (Sunday). This makes the leftmost
  // column a clean column rather than a ragged offset.
  const startDate = new Date(startMs)
  startDate.setHours(0, 0, 0, 0)
  const startDow = startDate.getDay()
  const gridStartMs = startMs - startDow * ONE_DAY_MS

  const cells: DayCell[] = []
  let weekIdx = 0
  for (let t = gridStartMs; t <= endMs; t += ONE_DAY_MS) {
    const d = new Date(t)
    const dayIdx = d.getDay()
    const iso = isoOf(t)
    cells.push({
      isoDate: iso,
      weekIdx,
      dayIdx,
      point: byDate.get(iso) ?? null,
    })
    if (dayIdx === 6) weekIdx += 1
  }
  const weekCount = weekIdx + 1
  return { cells, weekCount }
}

/* ------------------------------------------------------------------ */
/* Tooltip                                                              */
/* ------------------------------------------------------------------ */
function CellTooltip({
  cell,
  currency,
}: {
  cell: DayCell
  currency: string
}) {
  const niceDate = new Date(cell.isoDate + "T00:00:00").toLocaleDateString(
    "en-IN",
    { day: "numeric", month: "short", year: "numeric" },
  )

  if (!cell.point) {
    return (
      <div
        role="tooltip"
        className="pointer-events-none absolute z-30 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[11px] text-ink shadow-lg whitespace-nowrap"
        data-testid="mos-heatmap-tooltip"
      >
        <p className="font-medium">{niceDate}</p>
        <p className="text-caption">No data</p>
      </div>
    )
  }

  const mos = cell.point.mos_pct
  const sign = mos > 0 ? "+" : ""
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-30 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[11px] text-ink shadow-lg whitespace-nowrap min-w-[170px]"
      data-testid="mos-heatmap-tooltip"
    >
      <p className="mb-0.5 font-medium">{niceDate}</p>
      <div className="flex justify-between gap-3">
        <span className="text-caption">MoS</span>
        <span
          className={cn(
            "font-mono font-semibold",
            mos >= 0 ? "text-green-600" : "text-red-600",
          )}
        >
          {sign}
          {mos.toFixed(1)}%
        </span>
      </div>
      <div className="flex justify-between gap-3">
        <span className="text-caption">Fair value</span>
        <span className="font-mono">
          {formatCurrency(cell.point.fair_value, currency)}
        </span>
      </div>
      <div className="flex justify-between gap-3">
        <span className="text-caption">Price</span>
        <span className="font-mono">
          {formatCurrency(cell.point.price, currency)}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Range selector                                                       */
/* ------------------------------------------------------------------ */
function RangeSelector({
  value,
  onChange,
}: {
  value: MosHeatmapRange
  onChange: (next: MosHeatmapRange) => void
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Heat-map range"
      className="flex gap-1 rounded-lg bg-bg p-0.5"
    >
      {RANGE_OPTIONS.map((opt) => {
        const active = value === opt
        return (
          <button
            key={opt}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${opt} range`}
            onClick={() => onChange(opt)}
            className={cn(
              "text-xs px-2.5 py-1 rounded-md font-medium transition-colors min-w-[36px]",
              active
                ? "bg-brand text-white shadow-sm"
                : "text-caption hover:bg-border/40",
            )}
          >
            {opt}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Legend                                                               */
/* ------------------------------------------------------------------ */
function Legend() {
  return (
    <div
      data-testid="mos-heatmap-legend"
      className="mt-3 flex items-center gap-3 text-[11px] text-caption"
    >
      <span>FV gap:</span>
      <div className="flex items-center gap-1">
        <span className={cn("inline-block h-3 w-3 rounded-sm", PALETTE.negHigh)} />
        <span className={cn("inline-block h-3 w-3 rounded-sm", PALETTE.negMid)} />
        <span className={cn("inline-block h-3 w-3 rounded-sm", PALETTE.negLow)} />
        <span className="mx-1">negative</span>
      </div>
      <div className="flex items-center gap-1">
        <span className={cn("inline-block h-3 w-3 rounded-sm", PALETTE.neutral)} />
        <span>~0%</span>
      </div>
      <div className="flex items-center gap-1">
        <span className={cn("inline-block h-3 w-3 rounded-sm", PALETTE.posLow)} />
        <span className={cn("inline-block h-3 w-3 rounded-sm", PALETTE.posMid)} />
        <span className={cn("inline-block h-3 w-3 rounded-sm", PALETTE.posHigh)} />
        <span className="mx-1">positive</span>
      </div>
      <span className="ml-auto italic">Scale clamps at &plusmn;30%</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                       */
/* ------------------------------------------------------------------ */
export default function MosHeatmapCalendar({
  ticker,
  currency = "INR",
  historyOverride,
  className,
}: MosHeatmapCalendarProps) {
  const [range, setRange] = useState<MosHeatmapRange>("1Y")
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  // Years to request — round up so 3Y still has a buffer if the engine
  // hasn't backfilled the exact start date. We share the years=5 cache
  // key with ValuationTrajectoryChart for the 3Y view; smaller ranges
  // ride the same response.
  const { data, isLoading, isError } = useQuery<FVHistoryResponse>({
    queryKey: ["fv-history", ticker, 5],
    queryFn: () => getFVHistory(ticker, 5),
    enabled: !!ticker && !historyOverride,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  const rawHistory: FVHistoryPoint[] = historyOverride ?? data?.data ?? []
  const hasData = rawHistory.length > 0

  const { cells, weekCount } = useMemo(
    () => buildCells(rawHistory, range),
    [rawHistory, range],
  )

  // Summary chips — count of positive / negative / no-data days inside
  // the current range window so the user gets a one-line take-away
  // without having to read every cell.
  const summary = useMemo(() => {
    let pos = 0
    let neg = 0
    let zero = 0
    let noData = 0
    for (const c of cells) {
      if (!c.point) {
        noData += 1
        continue
      }
      const m = c.point.mos_pct
      if (m > 2) pos += 1
      else if (m < -2) neg += 1
      else zero += 1
    }
    const total = pos + neg + zero
    const pctPos = total > 0 ? Math.round((pos / total) * 100) : 0
    return { pos, neg, zero, noData, total, pctPos }
  }, [cells])

  const onCellClick = useCallback((cell: DayCell) => {
    if (!cell.point) return
    if (typeof window === "undefined") return
    window.dispatchEvent(
      new CustomEvent(MOS_HEATMAP_DAY_EVENT, {
        detail: { date: cell.isoDate, point: cell.point },
      }),
    )
  }, [])

  /* ---------- Render branches ---------- */
  if (isLoading && !historyOverride) {
    return (
      <section
        data-testid="mos-heatmap-calendar"
        data-state="loading"
        className={cn(
          "bg-surface rounded-2xl border border-border p-5",
          className,
        )}
      >
        <div className="h-5 w-44 bg-bg rounded animate-pulse mb-3" />
        <div className="h-[140px] bg-bg rounded-xl animate-pulse" />
      </section>
    )
  }

  if (isError && !historyOverride) {
    return (
      <section
        data-testid="mos-heatmap-calendar"
        data-state="error"
        className={cn(
          "bg-surface rounded-2xl border border-border p-5",
          className,
        )}
      >
        <h3 className="text-sm font-semibold text-ink mb-2">
          Margin-of-safety calendar
        </h3>
        <p className="text-xs text-caption">
          Calendar data unavailable right now. Refresh in a moment.
        </p>
      </section>
    )
  }

  if (!hasData) {
    return (
      <section
        data-testid="mos-heatmap-calendar"
        data-state="empty"
        className={cn(
          "bg-surface rounded-2xl border border-border p-5",
          className,
        )}
      >
        <h3 className="text-sm font-semibold text-ink mb-2">
          Margin-of-safety calendar
        </h3>
        <p className="text-xs text-caption">
          Calendar fills in as the engine recomputes this ticker. Check
          back after a few daily refreshes.
        </p>
      </section>
    )
  }

  // Layout constants — cell + gap. Total grid width is weekCount × 13px.
  const cellSize = 11
  const gap = 2
  const gridWidth = weekCount * (cellSize + gap)

  return (
    <section
      data-testid="mos-heatmap-calendar"
      data-state="ready"
      className={cn(
        "bg-surface rounded-2xl border border-border p-5",
        className,
      )}
    >
      <header className="flex items-center justify-between mb-3 gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Margin-of-safety calendar
          </h3>
          <p className="text-[11px] text-caption mt-0.5">
            One cell per day. Greener = FV above price; redder = FV below
            price. Click a cell to inspect the trajectory chart on that
            date.
          </p>
        </div>
        <RangeSelector value={range} onChange={setRange} />
      </header>

      <div
        data-testid="mos-heatmap-summary"
        className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-body"
      >
        <span>
          <span className="font-semibold text-green-600">{summary.pos}</span>{" "}
          days with positive FV gap
        </span>
        <span>
          <span className="font-semibold text-red-600">{summary.neg}</span>{" "}
          days with negative FV gap
        </span>
        <span className="text-caption">
          {summary.zero} near-zero &middot; {summary.noData} no-data
        </span>
        <span className="ml-auto text-caption">
          {summary.pctPos}% of tracked days had FV above price
        </span>
      </div>

      <div
        data-testid="mos-heatmap-grid-wrap"
        className="relative overflow-x-auto pb-2"
      >
        <div
          role="grid"
          aria-label={`Margin-of-safety calendar for ${ticker}`}
          className="relative"
          style={{
            width: gridWidth,
            height: 7 * (cellSize + gap),
          }}
        >
          {cells.map((cell, idx) => {
            const left = cell.weekIdx * (cellSize + gap)
            const top = cell.dayIdx * (cellSize + gap)
            const swatch = swatchFor(cell.point?.mos_pct ?? null)
            const interactive = !!cell.point
            return (
              <button
                key={cell.isoDate}
                type="button"
                role="gridcell"
                aria-label={
                  cell.point
                    ? `${cell.isoDate}: MoS ${cell.point.mos_pct.toFixed(1)}%`
                    : `${cell.isoDate}: no data`
                }
                disabled={!interactive}
                onMouseEnter={() => setHoverIdx(idx)}
                onFocus={() => setHoverIdx(idx)}
                onMouseLeave={() =>
                  setHoverIdx((cur) => (cur === idx ? null : cur))
                }
                onBlur={() =>
                  setHoverIdx((cur) => (cur === idx ? null : cur))
                }
                onClick={() => onCellClick(cell)}
                data-testid="mos-heatmap-cell"
                data-iso={cell.isoDate}
                data-has-data={interactive ? "true" : "false"}
                className={cn(
                  "absolute rounded-[2px] focus:outline-none focus:ring-1 focus:ring-brand transition-transform",
                  swatch,
                  interactive
                    ? "hover:scale-125 cursor-pointer"
                    : "cursor-default",
                )}
                style={{
                  width: cellSize,
                  height: cellSize,
                  left,
                  top,
                }}
              />
            )
          })}

          {/* Tooltip — absolutely positioned near the hovered cell. */}
          {hoverIdx != null && cells[hoverIdx] && (
            <div
              className="absolute"
              style={{
                left: Math.min(
                  cells[hoverIdx].weekIdx * (cellSize + gap) + cellSize + 6,
                  gridWidth - 200,
                ),
                top: Math.max(
                  cells[hoverIdx].dayIdx * (cellSize + gap) - 6,
                  0,
                ),
              }}
            >
              <CellTooltip cell={cells[hoverIdx]} currency={currency} />
            </div>
          )}
        </div>
      </div>

      <Legend />
    </section>
  )
}
